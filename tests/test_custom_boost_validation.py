from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime
import importlib.util
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from awcc_linux.models import AwccFan, CapabilityReport, ControlState, Fan, ProfileState, SystemSnapshot, Temperature

RESEARCH=Path(__file__).resolve().parents[1]/"research"
spec=importlib.util.spec_from_file_location("custom_boost_validation_test",RESEARCH/"custom_boost_validation.py")
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
spec2=importlib.util.spec_from_file_location("custom_boost_capture_test",RESEARCH/"run_custom_boost_validation.py")
capture=importlib.util.module_from_spec(spec2)
with patch.dict(sys.modules,{"custom_boost_validation":probe}):
    spec2.loader.exec_module(capture)
spec3=importlib.util.spec_from_file_location("fan3_timed_retry_test",RESEARCH/"run_fan3_timed_retry.py")
retry_capture=importlib.util.module_from_spec(spec3)
with patch.dict(sys.modules,{"custom_boost_validation":probe}):
    spec3.loader.exec_module(retry_capture)


def state(profile="custom",boost=100):
    return SystemSnapshot(datetime.now(),"Alienware x17 R1","1.27.0","7.0.0-38-generic",
        ProfileState(profile,("balanced","performance","low-power","custom")),
        fans=tuple(Fan(i,"Fan",2000,pwm_enable=2) for i in range(1,5)),
        awcc_fans=tuple(AwccFan(i,"Fan",2000,0,1000,boost) for i in range(1,5)),
        temperatures=(Temperature(1,"CPU",45,"AWCC WMI"),Temperature(1,"GPU",40,"NVIDIA NVML")),
        capabilities=CapabilityReport(True,True,False,ControlState.BIOS_AUTO))


class CustomBoostSafetyTests(unittest.TestCase):
    def test_fan3_retry_requires_separate_exact_confirmation_and_nonroot_caller(self):
        with patch.object(retry_capture.subprocess,"Popen") as run:
            for args in ([],[probe.CONFIRM],[retry_capture.CONFIRM,"--channel","2"],
                         [retry_capture.CONFIRM,"--channel","3"]):
                self.assertEqual(retry_capture.main(args),64)
            with patch.object(retry_capture.os,"geteuid",return_value=0):
                self.assertEqual(retry_capture.main([retry_capture.CONFIRM]),64)
            run.assert_not_called()
        self.assertEqual(retry_capture.ROOT_CONFIRM,probe.CONFIRM)

    def test_fan3_retry_pins_target_and_uses_a_new_exclusive_log(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory)/"results").mkdir()
            child=Mock()
            child.stdout=iter(['{"event":"fan3-retry-unit-test"}\n'])
            child.wait.return_value=0
            process=Mock()
            process.__enter__=Mock(return_value=child)
            process.__exit__=Mock(return_value=False)
            with patch.object(retry_capture,"__file__",str(Path(directory)/"capture.py")),patch.object(retry_capture.os,"geteuid",return_value=1000),patch.object(retry_capture.subprocess,"Popen",return_value=process) as run:
                self.assertEqual(retry_capture.main([retry_capture.CONFIRM]),0)
                self.assertEqual(run.call_args.args[0][-3:],[probe.CONFIRM,"--channel","3"])
                result=Path(directory)/"results/hardware-test-custom-boost-2026-10-15-fan3-retry1.jsonl"
                self.assertEqual(result.read_text(),'{"event":"fan3-retry-unit-test"}\n')
                with self.assertRaises(FileExistsError):
                    retry_capture.main([retry_capture.CONFIRM])
                self.assertEqual(run.call_count,1)

    def test_approved_twenty_second_stages_keep_the_original_watchdog_limit(self):
        self.assertEqual(probe.STAGE_SECONDS,20)
        self.assertEqual(probe.CUSTOM_SECONDS,75)
        self.assertLess(3*probe.STAGE_SECONDS+2,probe.CUSTOM_SECONDS)
        self.assertEqual(probe.LEVELS,(("A1",64),("B",100),("A2",64)))
        self.assertEqual(probe.CONFIRM,capture.CONFIRM)

    def test_only_explicitly_approved_remaining_channel_is_accepted(self):
        for channel in (2,3,4):
            self.assertEqual(probe.approved_channel([probe.CONFIRM,"--channel",str(channel)]),channel)
        for args in ([],[probe.CONFIRM],[probe.CONFIRM,"--channel","1"],
                     [probe.CONFIRM,"--channel","5"],[probe.CONFIRM,"--channel","02"],
                     [probe.CONFIRM,"--channel","2","--channel","3"],
                     ["--confirm-x17r1-custom-boost-64-100-64-20s","--channel","2"]):
            with self.subTest(args=args):
                self.assertIsNone(probe.approved_channel(args))
                with patch.object(probe.tempfile,"mkdtemp") as create:
                    self.assertEqual(probe.main(args),64)
                    create.assert_not_called()

    def test_each_channel_holds_the_other_three_at_100(self):
        for channel in (2,3,4):
            expected={i:64 if i==channel else 100 for i in range(1,5)}
            self.assertEqual(probe.stage_boosts(channel,64),expected)
            self.assertEqual(probe.stage_boosts(channel,100),dict.fromkeys(range(1,5),100))
            result=probe.assess({"A1":[1500]*20,"B":[2000]*20,"A2":[1500]*20},channel)
            self.assertTrue(result["responsive"])
            self.assertEqual(result["channel"],channel)
            self.assertIn(f"fan{channel} only",result["scope"])
        for channel,level in ((0,64),(5,100),(2,0),(3,255)):
            with self.assertRaises(ValueError):
                probe.stage_boosts(channel,level)

    def test_confirmation_and_privilege_guards_precede_all_work(self):
        with patch.object(probe.tempfile,"mkdtemp") as create:
            self.assertEqual(probe.main([]),64)
            with patch.object(probe.os,"geteuid",return_value=1000):
                self.assertEqual(probe.main([probe.CONFIRM,"--channel","2"]),64)
            create.assert_not_called()
        with patch.object(capture.subprocess,"Popen") as run:
            self.assertEqual(capture.main([]),64)
            with patch.object(capture.os,"geteuid",return_value=0):
                self.assertEqual(capture.main([capture.CONFIRM,"--channel","2"]),64)
            run.assert_not_called()

    def test_capture_selects_one_channel_and_never_overwrites_its_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory)/"results").mkdir()
            child=Mock()
            child.stdout=iter(['{"event":"unit-test"}\n'])
            child.wait.return_value=0
            process=Mock()
            process.__enter__=Mock(return_value=child)
            process.__exit__=Mock(return_value=False)
            with patch.object(capture,"__file__",str(Path(directory)/"capture.py")),patch.object(capture.os,"geteuid",return_value=1000),patch.object(capture.subprocess,"Popen",return_value=process) as run:
                args=[capture.CONFIRM,"--channel","3"]
                self.assertEqual(capture.main(args),0)
                self.assertEqual(run.call_args.args[0][-3:],[capture.CONFIRM,"--channel","3"])
                transcript=Path(directory)/"results/hardware-test-custom-boost-2026-10-15-fan3.jsonl"
                self.assertEqual(transcript.read_text(),'{"event":"unit-test"}\n')
                with self.assertRaises(FileExistsError):
                    capture.main(args)
                self.assertEqual(run.call_count,1)

    def test_valid_awcc_state_does_not_require_smm_manual_mode(self):
        probe.validate(state(),True,70,expected_profile="custom",expected_boosts={i:100 for i in range(1,5)},require_spinning=True)

    def test_ac_controller_model_and_profile_changes_abort(self):
        s=state()
        invalid=(replace(s,model="Other"),replace(s,bios_version="new"),
                 replace(s,profile=ProfileState("balanced")),
                 replace(s,capabilities=replace(s.capabilities,external_awccd_controller=True)))
        for changed in invalid:
            with self.subTest(changed=changed),self.assertRaises(RuntimeError):
                probe.validate(changed,True,70,expected_profile="custom")
        with self.assertRaises(RuntimeError):
            probe.validate(s,False,70)

    def test_missing_wrong_source_nonfinite_and_hot_sensor_abort(self):
        s=state()
        for sensors in (s.temperatures[:1],(s.temperatures[0],Temperature(2,"GPU",40,"AWCC WMI")),
                        (Temperature(1,"CPU",float("nan"),"AWCC WMI"),s.temperatures[1]),
                        (Temperature(1,"CPU",70,"AWCC WMI"),s.temperatures[1]),
                        (Temperature(1,"CPU",55,"AWCC WMI"),s.temperatures[1])):
            with self.subTest(sensors=sensors),self.assertRaises(RuntimeError):
                probe.validate(replace(s,temperatures=sensors),True,70,baseline_hot=45)

    def test_fan_topology_readback_and_stopped_fan_abort(self):
        s=state()
        for fans in (s.awcc_fans[:3],(replace(s.awcc_fans[0],rpm=None),)+s.awcc_fans[1:],
                     (replace(s.awcc_fans[0],boost=99),)+s.awcc_fans[1:],
                     (replace(s.awcc_fans[0],rpm=0),)+s.awcc_fans[1:]):
            with self.subTest(fans=fans),self.assertRaises(RuntimeError):
                probe.validate(replace(s,awcc_fans=fans),True,70,expected_boosts={i:100 for i in range(1,5)},require_spinning=True)

    def test_directional_repeatable_rpm_change_passes_without_fan_max(self):
        result=probe.assess({"A1":[2000]*12,"B":[3100]*12,"A2":[2100]*12})
        self.assertTrue(result["responsive"])
        self.assertEqual(result["increase_rpm"],1100)

    def test_constant_rpm_single_spike_or_slow_drift_never_pass(self):
        for phases in ({"A1":[2000]*12,"B":[2000]*12,"A2":[2000]*12},
                       {"A1":[2000]*12,"B":[2000]*11+[5000],"A2":[2000]*12},
                       {"A1":[2000]*12,"B":[3000]*12,"A2":[3500]*12},
                       {"A1":[2000]*2,"B":[3000]*12,"A2":[2000]*12}):
            self.assertFalse(probe.assess(phases)["responsive"])

    def test_run2_initial_coastdown_does_not_pass_the_predeclared_stability_gate(self):
        result=probe.assess({
            "A1":[4800,4600,4500,4500,4300,4200,4100,3900,3900,3700,3700,3500],
            "B":[3400,3500,3600,3800,3800,3900,4100,4100,4100,4100,4100,4100],
            "A2":[4000,4000,3900,3800,3600,3500,3400,3300,3300,3300,3300,3300],
        })
        self.assertEqual(result["median_rpm"],{"A1":3700,"B":4100,"A2":3300})
        self.assertEqual(result["increase_rpm"],400)
        self.assertEqual(result["decrease_rpm"],800)
        self.assertTrue(result["repeated_low"])
        self.assertFalse(result["stable_tails"])
        self.assertFalse(result["responsive"])

    def test_run3_twenty_second_measured_series_passes_unchanged_evaluator(self):
        result=probe.assess({
            "A1":[2000,2100,2300,2500,2700,2800,2900,3100]+[3300]*12,
            "B":[3300,3400,3500,3600,3700,3900,4000,4100,4000,4200]+[4100]*10,
            "A2":[4000,3900,3800,3700,3600,3500,3400]+[3300]*13,
        })
        self.assertEqual(result["median_rpm"],{"A1":3300,"B":4100,"A2":3300})
        self.assertEqual(result["increase_rpm"],800)
        self.assertEqual(result["decrease_rpm"],800)
        self.assertEqual(result["minimum_delta_rpm"],330)
        self.assertTrue(result["stable_tails"])
        self.assertTrue(result["repeated_low"])
        self.assertTrue(result["responsive"])

    def test_fan3_timed_retry_measured_series_passes_without_loosening_gates(self):
        measured={
            "A1":[0,2200,2300,2100,1900,1800]+[1700]*14,
            "B":[1700,1800,2000,2200,2500]+[2700]*15,
            "A2":[2800,2600,2300,2200,2000,1800]+[1700]*14,
        }
        self.assertTrue(all(len(v)==20 for v in measured.values()))
        result=probe.assess(measured,3)
        self.assertTrue(result["responsive"])
        self.assertTrue(result["stable_tails"])
        self.assertTrue(result["repeated_low"])
        self.assertEqual(result["channel"],3)
        self.assertEqual(result["median_rpm"],{"A1":1700,"B":2700,"A2":1700})
        self.assertEqual(result["increase_rpm"],1000)
        self.assertEqual(result["decrease_rpm"],1000)
        self.assertEqual(result["minimum_delta_rpm"],300)

    def test_remaining_channel_measured_series_preserve_pass_and_incomplete_results(self):
        measured={
            2:{"A1":[4700,4700,4500,4400,4300,4200,4000,3900,3800,3700,3500,3500,3300]+[3200]*7,
               "B":[3200,3300,3400,3500,3600,3800,3900]+[4100]*13,
               "A2":[4100,3900,3800,3700,3600,3500,3300]+[3200]*13},
            3:{"A1":[2400,2200,2000,1800]+[1700]*16,
               "B":[1700,1800,2000,2200,2500]+[2700]*15,"A2":[2700,2600]},
            4:{"A1":[2300,2200,2100,1900,1700,1500,1300]+[1200]*13,
               "B":[1200,1400,1500,1700,1800]+[2000]*15,
               "A2":[2000,1900,1700,1600,1400]+[1200]*15},
        }
        for channel,medians,delta in ((2,{"A1":3200,"B":4100,"A2":3200},900),
                                      (4,{"A1":1200,"B":2000,"A2":1200},800)):
            with self.subTest(channel=channel):
                self.assertTrue(all(len(v)==20 for v in measured[channel].values()))
                result=probe.assess(measured[channel],channel)
                self.assertTrue(result["responsive"])
                self.assertEqual(result["median_rpm"],medians)
                self.assertEqual(result["increase_rpm"],delta)
                self.assertEqual(result["decrease_rpm"],delta)
        result=probe.assess(measured[3],3)
        self.assertFalse(result["responsive"])
        self.assertEqual(result["reason"],"Insufficient independent stage samples")

    def make_fake_probe(self,directory):
        p=object.__new__(probe.Probe)
        p.channel=2
        p.state_dir=Path(directory)
        p.cancel=p.state_dir/"cancel"
        p.expired=p.state_dir/"expired"
        p.custom_deadline=p.state_dir/"custom.deadline"
        p.profile=p.state_dir/"profile"
        p.profile.write_text("custom")
        p.hwmon=p.state_dir
        p.original="performance"
        p.original_boosts={i:0 for i in range(1,5)}
        p.lock=Mock(side_effect=lambda _:nullcontext())
        p.event=Mock()
        p.set_ppd=Mock()
        p.write=Mock()
        p.daemon=Mock(return_value="performance")
        p.backend=Mock()
        p.backend.snapshot.return_value=state("performance",0)
        return p

    def test_recovery_bridges_ppd_then_restores_boosts_and_verifies(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(probe.time,"sleep"):
            p=self.make_fake_probe(directory)
            p.verify_pair=Mock(return_value=True)
            self.assertTrue(p.restore("unit"))
            self.assertEqual([call.args[0] for call in p.set_ppd.call_args_list],["balanced","performance"])
            self.assertEqual(p.write.call_count,4)
            self.assertTrue(p.cancel.exists())

    def test_whole_run_changes_and_measures_only_selected_channel_after_initialization(self):
        for channel in (2,3,4):
            with self.subTest(channel=channel),tempfile.TemporaryDirectory() as directory:
                p=self.make_fake_probe(directory)
                p.channel=channel
                p.ac=Mock(return_value=True)
                p.controllers=Mock()
                p.verify_pair=Mock(return_value=True)
                def sample(**validation):
                    boosts=validation.get("expected_boosts",dict.fromkeys(range(1,5),100))
                    fans=tuple(replace(f,boost=boosts[f.channel],rpm=(1500 if boosts[f.channel]==64 else 2000) if f.channel==channel else 3000) for f in state().awcc_fans)
                    return replace(state(validation["expected_profile"]),awcc_fans=fans)
                p.sample=Mock(side_effect=sample)
                p.restore=Mock(side_effect=lambda actor:p.cancel.touch() or True)
                with patch.object(probe.os,"fork",return_value=12345),patch.object(probe.os,"waitpid"),patch.object(probe.signal,"signal"),patch.object(probe.time,"monotonic",return_value=100),patch.object(probe.time,"sleep"),patch.object(probe.Path,"read_text",autospec=True,side_effect=lambda path:probe.DRIVER if path.name=="srcversion" else "Alienware"):
                    self.assertEqual(p.run(),0)
                writes=[(call.args[0].name,call.args[1]) for call in p.write.call_args_list]
                self.assertEqual(writes,[("profile","custom")]+[(f"fan{i}_boost",100) for i in range(1,5)]+[(f"fan{channel}_boost",level) for _,level in probe.LEVELS])
                stage_samples=[call for call in p.event.call_args_list if call.args[0]=="stage-sample"]
                self.assertEqual(len(stage_samples),60)
                evaluation=next(call.kwargs for call in p.event.call_args_list if call.args[0]=="evaluation")
                self.assertTrue(evaluation["responsive"])
                self.assertEqual(evaluation["channel"],channel)
                self.assertEqual(evaluation["median_rpm"],{"A1":1500,"B":2000,"A2":1500})
                p.restore.assert_called_once_with("parent")

    def test_failed_recovery_never_cancels_watchdog_or_writes_zero_in_custom(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(probe.time,"sleep"):
            p=self.make_fake_probe(directory)
            p.verify_pair=Mock(return_value=False)
            self.assertFalse(p.restore("unit"))
            self.assertFalse(p.cancel.exists())
            boost_values=[call.args[1] for call in p.write.call_args_list if "boost" in call.args[0].name]
            self.assertEqual(boost_values,[100]*4)

    def test_expired_probe_fences_test_write_but_allows_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            p=self.make_fake_probe(directory)
            del p.write
            p.expired.touch()
            target=Path(directory)/"test-node"
            with self.assertRaises(RuntimeError):
                p.write(target,64)
            self.assertFalse(target.exists())
            p.write(target,100,recovery=True)
            self.assertEqual(target.read_text().strip(),"100")

    def test_native_write_timing_adds_no_extra_hardware_write(self):
        with tempfile.TemporaryDirectory() as directory:
            p=self.make_fake_probe(directory)
            del p.write
            target=Mock()
            target.name="fan4_boost"
            with patch.object(probe.time,"monotonic",side_effect=[100,128]):
                p.write(target,64)
            target.write_text.assert_called_once_with("64\n")
            self.assertEqual(p.event.call_args_list[-1].args,("native-write-finished",))
            self.assertEqual(p.event.call_args_list[-1].kwargs["elapsed"],28)
            target.write_text.reset_mock()
            target.write_text.side_effect=OSError("failed")
            with self.assertRaises(OSError):
                p.write(target,100)
            target.write_text.assert_called_once_with("100\n")

    def test_incomplete_final_phase_is_not_a_success_even_after_restoration(self):
        with tempfile.TemporaryDirectory() as directory:
            p=self.make_fake_probe(directory)
            p.channel=3
            p.ac=Mock(return_value=True)
            p.controllers=Mock()
            p.verify_pair=Mock(return_value=True)
            p.sample=Mock(return_value=state())
            def interrupt_last_phase(event,**data):
                if event=="stage-sample" and data["phase"]=="A2" and data["sample"]==2:
                    raise RuntimeError("Interrupted 15; restoring original")
            p.event=Mock(side_effect=interrupt_last_phase)
            p.restore=Mock(side_effect=lambda actor:p.cancel.touch() or True)
            with patch.object(probe.os,"fork",return_value=12345),patch.object(probe.os,"waitpid"),patch.object(probe.signal,"signal"),patch.object(probe.time,"monotonic",return_value=100),patch.object(probe.time,"sleep"),patch.object(probe.Path,"read_text",autospec=True,side_effect=lambda path:probe.DRIVER if path.name=="srcversion" else "Alienware"),patch.object(probe,"assess") as evaluator:
                self.assertEqual(p.run(),1)
            evaluator.assert_not_called()
            completion=next(call.kwargs for call in p.event.call_args_list if call.args[0]=="test-complete")
            self.assertIsNone(completion["responsive"])
            self.assertEqual(completion["outcome"],"aborted")
            self.assertTrue(completion["restored"])

    def test_deadline_is_published_atomically(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(probe.time,"monotonic",return_value=100):
            p=self.make_fake_probe(directory)
            p.arm_custom_deadline(75)
            self.assertEqual(float(p.custom_deadline.read_text()),175)
            self.assertFalse((p.state_dir/"custom.deadline.next").exists())

    def test_failed_cooling_never_enters_custom_and_reports_not_tested(self):
        with tempfile.TemporaryDirectory() as directory:
            p=self.make_fake_probe(directory)
            hot=replace(state("performance",0),temperatures=(Temperature(1,"CPU",55,"AWCC WMI"),Temperature(1,"GPU",40,"NVIDIA NVML")))
            p.backend.snapshot.return_value=hot
            p.ac=Mock(return_value=True)
            p.controllers=Mock()
            p.sample=Mock(return_value=hot)
            p.verify_pair=Mock(return_value=True)
            p.restore=Mock(side_effect=lambda actor:p.cancel.touch() or True)
            with patch.object(probe.os,"fork",return_value=12345),patch.object(probe.os,"waitpid"),patch.object(probe.signal,"signal"),patch.object(probe.time,"monotonic",side_effect=[0,100]),patch.object(probe.Path,"read_text",autospec=True,side_effect=lambda path:probe.DRIVER if path.name=="srcversion" else "Alienware"):
                self.assertEqual(p.run(),1)
            p.write.assert_not_called()
            p.restore.assert_called_once_with("parent")
            completion=next(call.kwargs for call in p.event.call_args_list if call.args[0]=="test-complete")
            self.assertFalse(completion["custom_requested"])
            self.assertIsNone(completion["responsive"])
            self.assertEqual(completion["outcome"],"not-entered-custom")
