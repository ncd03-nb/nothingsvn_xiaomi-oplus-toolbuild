# NothingsVN Xiaomi → OPlus Toolbuild

Pipeline Linux tự động ghép ColorOS/OxygenOS/OPlus ROM lên thiết bị Xiaomi và
kết nối GitHub Actions với bot Telegram. Firmware phần cứng của Xiaomi được giữ
lại; framework OPlus được lấy từ ROM port.

## Luồng port

1. Tải và giải nén `payload.bin` của ROM stock Xiaomi và ROM OPlus.
2. Giữ `vendor`, `odm`, `*_dlkm`, firmware/boot image của Xiaomi.
3. Dùng `system`, `product`, `system_ext` của OPlus; gộp các partition `my_*`
   vào gốc system để các dòng `import /my_*/build.prop` hoạt động.
4. Chép `vendor/etc/passwd` và `group` từ OPlus để sửa SIM 2/dịch vụ OPlus.
5. Tự dò CPU, model, camera, màn hình và `first_api_level` từ ROM Xiaomi, sau
   đó ghi các thuộc tính tương ứng cùng thương hiệu OPPO vào ODM.
6. Áp dụng có điều kiện VNDK APEX, overlay, Bluetooth QTI và cryptoeng HAL.
7. Đọc dynamic group size từ metadata payload, tái tạo SELinux metadata, đóng
   các image EROFS/EXT4 và tạo ZIP flashable.

> ROM port có thể brick hoặc mất dữ liệu. Luôn có fastboot ROM đúng model, sao
> lưu dữ liệu và kiểm tra `super` size trước khi flash. Lần boot đầu nên thu
> `adb logcat`/AVC denial; không chuyển toàn bộ SELinux sang permissive.

## Build local

Yêu cầu Ubuntu 22.04/24.04 x86_64 và khoảng 80–120 GB trống:

```bash
sudo bash setup.sh
sudo bash build.sh \
  'https://example/Xiaomi-stock.zip' \
  'https://example/ColorOS15-full.zip' \
  y local/repo xiaomi-oplus 'Builder' ''
```

Kết quả nằm trong `out/ColorOS15_<codename>_<date>.zip`.

## Asset từ AyuGram

Các blob trong ảnh tham khảo không được commit vì có file lớn hơn 100 MB và
chưa rõ quyền phân phối. Trên máy Windows đã cung cấp, chạy:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\import-ayugram-assets.ps1
```

Script nhập `femboyAidL`, `overlay`, `system_ext/apex` và thư viện Bluetooth vào
`assets/local/` (đã gitignore). Bật từng nhóm bằng biến môi trường workflow.
Không bật overlay dấu vân tay của model khác nếu chưa kiểm tra resource/density.

Actions tải bundle từ release `assets-v1` của repo private
`ncd03-nb/nothingsvn-oplus-port-assets`. Khai báo token có quyền đọc repo này
bằng repository secret `PORT_ASSETS_TOKEN`; người dùng Telegram vẫn chỉ cần gửi
hai link ROM. Gốc archive chứa `femboyAidL/`, `overlay/`, `system_ext/` và
`vendor/`.

## GitHub Actions

Workflow `Xiaomi OPlus ROM Port` nhận:

- `input_url`: OTA Xiaomi cho thiết bị đích.
- `portrom_url`: OTA payload ColorOS/OxygenOS nguồn.
- `request_id`, `builder_name`, `builder_id`: bot tự truyền.
- hai cờ tùy chọn overlay và cryptoeng.

Secrets thông báo: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`. ZIP luôn được
đăng thành GitHub Actions artifact 7 ngày, không phụ thuộc Google Drive.

## Bot Telegram

Bot nằm ở repo workspace `nothingsvn-rom-bot`. Cấu hình `GITHUB_REPOSITORY`
trỏ tới repo toolbuild này, sau đó dùng duy nhất hai link:

```text
/bp <xiaomi_url> -port <oplus_url>
```

Metadata thiết bị được lấy theo thứ tự: property trong ROM, file Xiaomi
`product/etc/device_features/<codename>.xml`, rồi catalog fallback
`devices/xiaomi.json` cho thông số vật lý không có trong Android (đặc biệt là
kích thước đường chéo màn hình). Vì vậy lệnh bot vẫn không cần profile thiết bị.

Build log hiển thị riêng từng pha download, unpack payload, unpack từng
partition, nhận diện thiết bị, port, repack và tạo super/ZIP. Tác vụ dài có
heartbeat mỗi 30 giây với thời gian, dung lượng đã tạo và ổ đĩa còn trống.

## Sửa lỗi thực tế đã tích hợp

- SIM 2: đồng bộ `vendor/etc/passwd` và `group` từ OPlus.
- Breeno “device not supported”: ODM brand/manufacturer = `OPPO`, kể cả file
  `*build.prop` riêng của codename.
- About phone: CPU/model/camera/screen và battery capacity dò từ ROM Xiaomi.
- VNDK thiếu: chép các `com.android.vndk.v*.apex` có trong asset.
- Crypto/privacy: module `femboyAidL` tùy chọn và context HAL allocator.
- Property context: chỉ thêm key đã quan sát qua `PROPERTY_CONTEXT_PATCH_FILE`;
  có thể dùng `u:object_r:exported_system_prop:s0`, không blanket patch.
- NFC: mặc định giữ toàn bộ vendor/ODM Xiaomi. Các chỉnh sửa APK (logo,
  `ifaamanager.jar`, nền Settings) không tự động vì phụ thuộc phiên bản và chữ ký.

Nguồn tham khảo: `tiencv2006/nothingsvn_xiaomi-toolbuild`, hai toolbuild OPlus
trong workspace, tài liệu ColorOS vendor/BBK đã cung cấp và asset AyuGram.
