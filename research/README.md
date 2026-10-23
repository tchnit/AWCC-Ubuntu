# Nghiên cứu phần cứng

Các script trong thư mục này dành cho chẩn đoán có kiểm soát trên Alienware
x17 R1; một số script có thể gửi lệnh thật nếu được chạy với tham số xác nhận.
Không chạy chúng như một phần của cài đặt hoặc test suite thông thường.

Repo giữ phần mã nguồn alienware_wmi đã tách từ Ubuntu HWE trong
sources/ubuntu-hwe-7.0/alienware/ để so sánh offline và chạy các source test.
Các archive kernel lớn, module .ko đã build và file Module.symvers được tạo
lại cục bộ và không đưa lên Git. Những bản sao kernel giữ SPDX/copyright gốc
và bản GPL-2.0 trong ../LICENSES/GPL-2.0.txt; chúng không phải mã gốc của
ứng dụng.

results/ là bằng chứng cục bộ: ACPI dump, JSONL, ảnh, bản backup source và
package theo từng lần thử. Thư mục này bị .gitignore loại vì có dữ liệu cụ
thể của máy/người dùng và không cần để chạy ứng dụng. Test đối chiếu DSDT sẽ
skip nếu thiếu bảng đã lưu; những test còn lại dùng fixture tổng hợp hoặc
source có trong repo. Báo cáo trong docs/ có thể nhắc đến các log này nhưng
không thay thế chúng bằng kết quả giả.
