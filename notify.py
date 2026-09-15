import os
import sys
import html
import random
import re
import string
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

# Giữ stdout/stderr ở UTF-8 trên GitHub runner và terminal cục bộ.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

FINAL_STATUSES = {"success", "fail", "cancelled"}
STATUS_ALIASES = {
    "failure": "fail",
    "failed": "fail",
    "error": "fail",
    "cancel": "cancelled",
    "canceled": "cancelled",
    "cancelled": "cancelled",
}

STATUS_INFO = {
    "start": ("BẮT ĐẦU", "KHỞI TẠO MÔI TRƯỜNG BUILD", "Đang chuẩn bị runner, biến môi trường và thư mục làm việc."),
    "sync": ("ĐỒNG BỘ", "ĐỒNG BỘ DỮ LIỆU", "Đang đồng bộ hoặc tải dữ liệu nguồn cần thiết."),
    "download": ("TẢI ROM", "TẢI SOURCE ROM", "Đang tải source ROM về runner để xử lý."),
    "unpack": ("GIẢI NÉN", "GIẢI NÉN PHÂN VÙNG", "Đang giải nén payload/new.dat/super image và các phân vùng liên quan."),
    "build": ("BUILD", "BUILD VÀ PATCH ROM", "Đang xử lý, chỉnh sửa, vá và tối ưu các thành phần ROM."),
    "pack": ("ĐÓNG GÓI", "ĐÓNG GÓI ROM ZIP", "Đang repack phân vùng và tạo gói ROM có thể flash."),
    "upload": ("TẢI LÊN", "TẢI LÊN THÀNH PHẨM", "Đang upload file ROM đã build xong lên nơi lưu trữ."),
    "success": ("HOÀN TẤT", "BUILD HOÀN TẤT", "Quy trình build ROM đã hoàn tất thành công."),
    "fail": ("THẤT BẠI", "BUILD GẶP LỖI", "Có lỗi xảy ra trong quá trình build. Xem phần chẩn đoán bên dưới."),
    "cancelled": ("ĐÃ HỦY", "BUILD ĐÃ BỊ HỦY", "Workflow đã bị hủy hoặc dừng trước khi hoàn tất."),
}

STATUS_EMOJI = {
    "start": "🚀",
    "sync": "🔄",
    "download": "⬇️",
    "unpack": "📂",
    "build": "🔧",
    "pack": "📦",
    "upload": "☁️",
    "success": "✅",
    "fail": "❌",
    "cancelled": "⛔",
}

STAGES = [
    ("start", "Khởi tạo"),
    ("sync", "Đồng bộ"),
    ("download", "Tải ROM"),
    ("unpack", "Giải nén"),
    ("build", "Build"),
    ("pack", "Đóng gói"),
    ("upload", "Tải lên"),
    ("success", "Hoàn tất"),
]

STATUS_ACTIONS = {
    "start": "Không cần thao tác; hệ thống đang chuẩn bị môi trường build.",
    "sync": "Nếu bước này đứng lâu, hãy kiểm tra nguồn dữ liệu hoặc kết nối mạng của runner.",
    "download": "Nếu tải chậm hoặc lỗi, hãy kiểm tra lại link source ROM và dung lượng trống của runner.",
    "unpack": "Nếu lỗi ở bước này, thường cần xem định dạng payload/new.dat/super image và dung lượng giải nén.",
    "build": "Đây là bước xử lý chính; nếu thất bại hãy xem đoạn log cuối để biết file hoặc lệnh gây lỗi.",
    "pack": "Nếu đóng gói thất bại, hãy kiểm tra cấu trúc phân vùng, dung lượng output và quyền ghi file.",
    "upload": "Nếu upload lâu, hãy kiểm tra kích thước file ROM và kết nối tới nơi lưu trữ.",
    "success": "Có thể kiểm tra file output/link tải và gửi ROM cho người yêu cầu.",
    "fail": "Mở build log để xem đầy đủ lỗi, đồng thời kiểm tra phần chẩn đoán trong thông báo này.",
    "cancelled": "Kiểm tra Timeline/Jobs, Run ID và Attempt trong GitHub Actions để biết thời điểm dừng.",
}

CONCLUSION_LABELS = {
    "success": "thành công",
    "failure": "thất bại",
    "failed": "thất bại",
    "cancelled": "đã hủy",
    "canceled": "đã hủy",
    "skipped": "đã bỏ qua",
    "timed_out": "hết thời gian",
    "action_required": "cần thao tác",
    "neutral": "trung lập",
}

UNKNOWN_VALUES = {
    "",
    "unknown",
    "none",
    "null",
    "n/a",
    "na",
    "pending",
    "detecting...",
    "scanning...",
    "không rõ",
    "khong ro",
    "chưa rõ",
    "chua ro",
}

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
MAX_LOG_DOCUMENT_BYTES = 45 * 1024 * 1024


def normalize_status(status: str) -> str:
    value = (status or "").strip().lower()
    return STATUS_ALIASES.get(value, value or "start")


def escape(value) -> str:
    return html.escape(str(value), quote=True)


def strip_ansi(value: str) -> str:
    return ANSI_RE.sub("", value or "")


def read_file_if_exists(path, default="") -> str:
    try:
        path = Path(path)
        if not path.exists() or not path.is_file():
            return default
        value = path.read_text(encoding="utf-8", errors="replace").strip()
        return value if value else default
    except Exception:
        return default


def read_first(paths, default="") -> str:
    for item in paths:
        value = read_file_if_exists(item)
        if is_available(value):
            return value
    return default


def write_file(path, value: str) -> None:
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(value), encoding="utf-8")
    except Exception:
        pass


def is_available(value) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    return text.lower() not in UNKNOWN_VALUES


def compact_one_line(value: str, max_len: int = 180) -> str:
    text = strip_ansi(str(value)).replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > max_len:
        text = text[: max_len - 3].rstrip() + "..."
    return text


def tail_text(path: Path, max_lines: int = 24, max_chars: int = 1400) -> str:
    try:
        if not path.exists() or not path.is_file():
            return ""
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        cleaned = [strip_ansi(line).rstrip() for line in lines if strip_ansi(line).strip()]
        text = "\n".join(cleaned[-max_lines:]).strip()
        if len(text) > max_chars:
            text = "...\n" + text[-max_chars:]
        return text
    except Exception:
        return ""


def collect_log_candidates():
    candidates = []
    env_log = os.environ.get("NOTIFY_ERROR_LOG", "")
    if env_log:
        for item in re.split(r"[;,]", env_log):
            item = item.strip()
            if item:
                candidates.append(item)

    runner_temp = os.environ.get("RUNNER_TEMP", "")
    if runner_temp:
        candidates.extend([
            str(Path(runner_temp) / "build_action.log"),
            str(Path(runner_temp) / "build_error.log"),
        ])

    candidates.extend([
        "build_action.log",
        "build.log",
        "build_error.log",
        "error.log",
        "last_error.log",
        "bin/ddevice/error_reason.txt",
        "bin/ddevice/error.log",
        "out/error.log",
    ])

    seen = set()
    result = []
    for item in candidates:
        path = Path(item)
        key = str(path.resolve()) if path.exists() else str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result




def format_file_size(size: int) -> str:
    try:
        size = int(size)
    except Exception:
        return "không rõ"
    units = ["B", "KiB", "MiB", "GiB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{size} B"


def safe_filename_part(value, default="build") -> str:
    text = compact_one_line(value, 80)
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-")
    return text or default


def select_full_log_path():
    for candidate in collect_log_candidates():
        try:
            if candidate.exists() and candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
        except Exception:
            continue
    return None


def compose_log_caption(status: str, repo_name: str, build_id: str, log_path: Path, size: int, part_index: int, total_parts: int) -> str:
    marker = STATUS_INFO.get(status, ("THÔNG TIN", "", ""))[0]
    lines = [
        "<b>Log lỗi build ROM</b>",
        f"• <b>Trạng thái:</b> <code>{escape(marker)}</code>",
        f"• <b>Mã build:</b> <code>{escape(build_id)}</code>",
        f"• <b>Dung lượng:</b> <code>{escape(format_file_size(size))}</code>",
    ]
    if total_parts > 1:
        lines.append(f"• <b>Phần:</b> <code>{part_index}/{total_parts}</code>")
    return "\n".join(lines)


def post_telegram_document_bytes(url: str, payload: dict, filename: str, content: bytes):
    with BytesIO(content) as file_data:
        files = {"document": (filename, file_data, "text/plain")}
        response = requests.post(url, data=payload, files=files, timeout=120)
    try:
        data = response.json()
    except Exception:
        data = {}
    return response, data


def send_error_log_document(base_url: str, chat_id: str, status: str, repo_name: str, build_id: str) -> bool:
    log_path = select_full_log_path()
    if not log_path:
        print("Không tìm thấy file log lỗi để gửi riêng cho người build.")
        return False

    try:
        size = log_path.stat().st_size
    except Exception as exc:
        print(f"Không thể đọc thông tin file log lỗi: {exc}")
        return False

    if size <= 0:
        print("File log lỗi đang trống; bỏ qua gửi file .txt.")
        return False

    total_parts = max(1, (size + MAX_LOG_DOCUMENT_BYTES - 1) // MAX_LOG_DOCUMENT_BYTES)
    base_name = f"{safe_filename_part(build_id)}_{safe_filename_part(status, 'status')}_error_log"
    sent_parts = 0

    try:
        with log_path.open("rb") as log_file:
            for part_index in range(1, total_parts + 1):
                content = log_file.read(MAX_LOG_DOCUMENT_BYTES)
                if not content:
                    break

                if total_parts > 1:
                    filename = f"{base_name}_part{part_index:02d}of{total_parts:02d}.txt"
                else:
                    filename = f"{base_name}.txt"

                payload = {
                    "chat_id": chat_id,
                    "caption": compose_log_caption(status, repo_name, build_id, log_path, size, part_index, total_parts),
                    "parse_mode": "HTML",
                    "disable_content_type_detection": "true",
                }
                response, data = post_telegram_document_bytes(f"{base_url}/sendDocument", payload, filename, content)
                if not response.ok:
                    description = str(data.get("description", response.text))
                    print(f"Không thể gửi log lỗi cho người build. Lý do: {description}")
                    return False

                sent_parts += 1
                if total_parts > 1:
                    print(f"Đã gửi log lỗi cho người build: {filename} ({part_index}/{total_parts}).")
                else:
                    print(f"Đã gửi log lỗi cho người build: {filename}.")
    except Exception as exc:
        print(f"Lỗi khi gửi log lỗi cho người build: {exc}")
        return False

    return sent_parts == total_parts


def extract_reason_from_log(log_tail: str) -> str:
    if not log_tail:
        return ""
    patterns = (
        "[error]",
        " error",
        "error:",
        "failed",
        "failure",
        "exception",
        "traceback",
        "fatal",
        "no space left",
        "permission denied",
        "command not found",
        "not found",
        "cannot",
        "unable",
    )
    lines = [line.strip() for line in log_tail.splitlines() if line.strip()]
    for line in reversed(lines):
        lower = line.lower()
        if any(pattern in lower for pattern in patterns):
            return compact_one_line(line)
    return compact_one_line(lines[-1]) if lines else ""


def collect_diagnostics(status: str):
    env_reason = (
        os.environ.get("NOTIFY_ERROR_REASON")
        or os.environ.get("ERROR_REASON")
        or os.environ.get("FAILURE_REASON")
        or os.environ.get("CANCEL_REASON")
        or ""
    )

    selected_path = ""
    selected_tail = ""
    for candidate in collect_log_candidates():
        tail = tail_text(candidate)
        if tail:
            selected_path = str(candidate)
            selected_tail = tail
            break

    reason = compact_one_line(env_reason) if env_reason else extract_reason_from_log(selected_tail)
    if not reason:
        if status == "cancelled":
            reason = "Workflow đã bị hủy trước khi hoàn tất; hãy kiểm tra Run ID và Attempt trong GitHub Actions."
        elif status == "fail":
            reason = "Không tìm thấy đoạn log cục bộ; hãy mở log GitHub Actions để xem chi tiết đầy đủ."

    return reason, selected_path, selected_tail


def build_action_url(repo_name: str) -> str:
    repo = repo_name or os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if repo and run_id:
        return f"https://github.com/{repo}/actions/runs/{run_id}"
    if repo:
        return f"https://github.com/{repo}/actions"
    return ""


def current_time_text() -> str:
    return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%Y-%m-%d %H:%M:%S GMT+7")


def localize_conclusion(value: str) -> str:
    text = compact_one_line(value)
    if not text:
        return ""
    return CONCLUSION_LABELS.get(text.lower(), text)


def read_gdrive_link() -> str:
    """Link Google Drive do upload_rom_api.py ghi lại sau khi upload xong."""
    return read_first([
        "bin/ddevice/gdrive_link.txt",
        "bin/ddevice/download_link.txt",
    ])


def collect_device_info():
    rom_os = read_first([
        "bin/ddevice/rom_os.txt",
        "bin/ddevice/brand_os.txt",
        "bin/ddevice/brand.txt",
        "bin/ddevice/os_type.txt",
    ])
    if rom_os in {"OS1", "OS2", "OS3"}:
        rom_os = "HyperOS"

    android_ver = read_file_if_exists("bin/ddevice/androidver.txt")
    sdk_level = read_file_if_exists("bin/ddevice/sdkLevel.txt")

    return {
        "Thiết bị": read_first([
            "bin/ddevice/device_name.txt",
            "bin/ddevice/name_devices.txt",
            "bin/ddevice/name_device.txt",
        ]),
        "Mã thiết bị": read_first([
            "bin/ddevice/device_code.txt",
            "bin/ddevice/device_model.txt",
            "bin/ddevice/device_f.txt",
        ]),
        "ROM nền": " | ".join(
            part
            for part in [
                rom_os,
                read_first([
                    "bin/ddevice/rom_version.txt",
                    "bin/ddevice/base_rom_code.txt",
                    "bin/ddevice/base_build_id.txt",
                ]),
            ]
            if is_available(part)
        ),
        "ROM port": " | ".join(
            part
            for part in [
                "ColorOS",
                read_file_if_exists("bin/ddevice/port_rom_code.txt"),
            ]
            if is_available(part)
        ),
        "Khu vực": read_first([
            "bin/ddevice/rom_region.txt",
            "bin/ddevice/device_type.txt",
        ]),
        "Android / SDK": " | ".join(
            part
            for part in [
                f"Android {android_ver}" if is_available(android_ver) else "",
                f"SDK {sdk_level}" if is_available(sdk_level) else "",
            ]
            if is_available(part)
        ),
        "Loại ROM": read_first(["bin/ddevice/romtype.txt"]),
        "Hệ thống file / cấu trúc": " | ".join(
            part
            for part in [
                read_first(["bin/ddevice/fstype.txt"]),
                read_first(["bin/script2flash/META-INF/Data/Structure"]),
            ]
            if is_available(part)
        ),
        "Chip": read_first(["bin/script2flash/META-INF/Data/Chip"]),
        "Phiên bản tool": read_first(["Version"]),
        "File output": read_first(["bin/ddevice/output_zip.txt"]),
        "Link tải": read_gdrive_link(),
    }


def collect_run_info(repo_name: str, build_id: str):
    sha = os.environ.get("GITHUB_SHA", "")
    sha_short = sha[:7] if sha else ""
    run_number = os.environ.get("GITHUB_RUN_NUMBER", "")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_parts = []
    if run_number:
        run_parts.append(f"#{run_number}")
    if run_attempt:
        run_parts.append(f"lần thử {run_attempt}")
    if run_id:
        run_parts.append(f"ID {run_id}")

    workflow = os.environ.get("GITHUB_WORKFLOW", "")
    job = os.environ.get("GITHUB_JOB", "")
    workflow_job = " / ".join(part for part in [workflow, job] if is_available(part))

    actor = os.environ.get("GITHUB_ACTOR", "")
    triggering_actor = os.environ.get("GITHUB_TRIGGERING_ACTOR", "")
    actor_text = actor
    if triggering_actor and triggering_actor != actor:
        actor_text = f"{actor} (kích hoạt qua: {triggering_actor})" if actor else triggering_actor

    ref = os.environ.get("GITHUB_REF_NAME", "") or os.environ.get("GITHUB_REF", "")
    ref_sha = " / ".join(part for part in [ref, sha_short] if is_available(part))

    return {
        "Mã build": build_id,
        "Kho lưu trữ": repo_name or os.environ.get("GITHUB_REPOSITORY", ""),
        "Lượt chạy": " / ".join(run_parts),
        "Workflow / Job": workflow_job,
        "Sự kiện": os.environ.get("GITHUB_EVENT_NAME", ""),
        "Nhánh / SHA": ref_sha,
        "Người kích hoạt": actor_text,
        "Runner": os.environ.get("RUNNER_NAME", ""),
        "Kết luận workflow": localize_conclusion(os.environ.get("NOTIFY_WORKFLOW_CONCLUSION", "")),
        "Cập nhật lúc": current_time_text(),
    }


def progress_block(status: str, previous_status: str = ""):
    """Trả về (dòng thanh tiến trình, dòng liệt kê các bước)."""
    stage_keys = [stage for stage, _ in STAGES]
    stage_labels = dict(STAGES)

    marker_status = previous_status if status in {"fail", "cancelled"} and previous_status else status
    marker_status = normalize_status(marker_status)
    current_index = stage_keys.index(marker_status) if marker_status in stage_keys else -1
    done = current_index + 1 if current_index >= 0 else 0

    bar = "▰" * done + "▱" * (len(STAGES) - done)
    label = stage_labels.get(marker_status, "Không rõ")
    if status == "fail":
        state = f"Dừng do lỗi tại {label}"
    elif status == "cancelled":
        state = f"Đã hủy tại {label}"
    elif status == "success":
        state = "Hoàn tất"
    else:
        state = label

    marks = []
    for idx, (_stage, name) in enumerate(STAGES):
        if idx < current_index:
            marks.append(f"✓{name}")
        elif idx == current_index:
            if status == "success":
                marks.append(f"✓{name}")
            elif status in {"fail", "cancelled"}:
                marks.append(f"✗{name}")
            else:
                marks.append(f"●{name}")
        else:
            marks.append(f"○{name}")

    bar_line = f"<code>{bar}</code> <b>{escape(state)}</b> · {done}/{len(STAGES)}"
    return bar_line, " ".join(marks)


def read_config_flag(key: str):
    """Đọc cờ build giống config_flag() trong functions.sh.

    Biến môi trường viết hoa cùng tên được ưu tiên hơn config.env, đúng như
    phía shell, để thông báo luôn phản ánh đúng cấu hình thực sự của lần build.
    """
    value = (os.environ.get(key.upper(), "") or "").strip()
    if not value:
        for line in read_file_if_exists("config.env").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                value = line.split("=", 1)[1].strip()
                break
    if not value:
        return None
    return value.lower() == "true"


def flag_label(value) -> str:
    if value is None:
        return ""
    return "✅ Bật" if value else "⛔ Tắt"


def add_section(lines, title: str, fields):
    body = []
    for label, value, code in fields:
        if not is_available(value):
            continue
        text = compact_one_line(str(value), 260)
        if code:
            body.append(f"• <b>{escape(label)}:</b> <code>{escape(text)}</code>")
        else:
            body.append(f"• <b>{escape(label)}:</b> {escape(text)}")
    if not body:
        return
    if lines:
        lines.append("")
    lines.append(f"<b>{escape(title)}</b>")
    lines.extend(body)


def clamp_message(lines, limit: int = 3900, budget: int = 3700) -> str:
    """Ghép các dòng lại, cắt theo nguyên dòng để không làm vỡ thẻ HTML."""
    message = "\n".join(lines)
    if len(message) <= limit:
        return message
    trimmed = []
    total = 0
    for line in lines:
        if total + len(line) + 1 > budget:
            break
        trimmed.append(line)
        total += len(line) + 1
    trimmed.extend(["", "<i>(Nội dung đã được rút gọn.)</i>"])
    return "\n".join(trimmed)


def compose_message(status, repo_name, rom_link, build_id, builder_name):
    status = normalize_status(status)
    _marker, status_title, status_desc = STATUS_INFO.get(
        status,
        ("THÔNG TIN", "CẬP NHẬT TRẠNG THÁI", f"Nhận được trạng thái: {status}"),
    )
    emoji = STATUS_EMOJI.get(status, "•")

    previous_status = read_file_if_exists("bin/ddevice/last_status.txt")
    if status not in FINAL_STATUSES:
        write_file("bin/ddevice/last_status.txt", status)

    action_url = build_action_url(repo_name)
    builder_text = builder_name if builder_name else "Hệ thống"
    device_info = collect_device_info()
    run_info = collect_run_info(repo_name, build_id)
    bar_line, stage_line = progress_block(status, previous_status)

    lines = [
        f"{emoji} <b>BUILD ROM · {escape(status_title)}</b>",
        f"<code>{escape(build_id)}</code>",
        "",
        bar_line,
        f"<i>{escape(stage_line)}</i>",
    ]

    add_section(lines, "📱 THIẾT BỊ", [
        ("Tên", device_info.get("Thiết bị"), True),
        ("Mã", device_info.get("Mã thiết bị"), True),
        ("ROM nền", device_info.get("ROM nền"), True),
        ("Android / SDK", device_info.get("Android / SDK"), True),
        ("Khu vực", device_info.get("Khu vực"), True),
        ("Chip", device_info.get("Chip"), True),
    ])

    add_section(lines, "⚙️ CẤU HÌNH BUILD", [
        ("Mod", flag_label(read_config_flag("install_mods")), False),
        ("Toolbox", flag_label(read_config_flag("install_toolbox")), False),
        ("Loại ROM", device_info.get("Loại ROM"), True),
        ("Hệ thống file", device_info.get("Hệ thống file / cấu trúc"), True),
        ("Phiên bản tool", device_info.get("Phiên bản tool"), True),
    ])

    add_section(lines, "🏗️ LƯỢT CHẠY", [
        ("Người build", builder_text, False),
        ("Kho lưu trữ", run_info.get("Kho lưu trữ"), True),
        ("Lượt chạy", run_info.get("Lượt chạy"), True),
        ("Nhánh / SHA", run_info.get("Nhánh / SHA"), True),
        ("Người kích hoạt", run_info.get("Người kích hoạt"), True),
        ("Kết luận workflow", run_info.get("Kết luận workflow"), True),
        ("Cập nhật lúc", run_info.get("Cập nhật lúc"), True),
    ])

    add_section(lines, "📦 KẾT QUẢ", [
        ("File output", device_info.get("File output"), True),
    ])

    if status in {"fail", "cancelled"}:
        reason, _log_path, _log_tail = collect_diagnostics(status)
        detail = (
            "Log lỗi được gửi riêng cho người build nếu có user ID."
            if status == "fail"
            else "Xem Build log trên GitHub Actions để biết thời điểm dừng."
        )
        add_section(lines, f"{emoji} CHẨN ĐOÁN", [
            ("Lý do", reason, True),
            ("Chi tiết", detail, False),
            ("Gợi ý", STATUS_ACTIONS.get(status), False),
        ])
    elif status == "success":
        add_section(lines, "🎉 HOÀN TẤT", [
            ("Kết quả", "Build hoàn tất, kiểm tra file output hoặc link tải.", False),
            ("Gợi ý", STATUS_ACTIONS.get(status), False),
        ])
    else:
        add_section(lines, "📝 TÓM TẮT", [
            ("Đang làm", status_desc, False),
            ("Lưu ý", STATUS_ACTIONS.get(status), False),
        ])

    link_lines = []
    gdrive_link = device_info.get("Link tải")
    if is_available(gdrive_link):
        link_text = device_info.get("File output") or "Tải xuống"
        link_lines.append(f"• <b>Tải ROM (Google Drive):</b> <a href=\"{escape(gdrive_link)}\">{escape(compact_one_line(link_text, 80))}</a>")
    if is_available(action_url):
        link_lines.append(f"• <b>Build log:</b> <a href=\"{escape(action_url)}\">GitHub Actions</a>")
    if is_available(rom_link):
        link_lines.append(f"• <b>Source ROM:</b> <a href=\"{escape(rom_link)}\">Source</a>")
    if link_lines:
        lines.append("")
        lines.append("<b>🔗 LIÊN KẾT</b>")
        lines.extend(link_lines)

    return clamp_message(lines)


def save_env(name: str, value: str) -> None:
    env_path = os.environ.get("GITHUB_ENV")
    if not env_path or not value:
        return
    try:
        with open(env_path, "a", encoding="utf-8") as env_file:
            env_file.write(f"{name}={value}\n")
    except Exception:
        pass


def post_telegram(url: str, payload: dict):
    response = requests.post(url, json=payload, timeout=25)
    try:
        data = response.json()
    except Exception:
        data = {}
    return response, data


def send_notification(status, repo_name, rom_link, channel_id, bot_token, msg_id=None, build_id="Không rõ", builder_name="", builder_id=""):
    status = normalize_status(status)
    message = compose_message(status, repo_name, rom_link, build_id, builder_name)

    base_url = f"https://api.telegram.org/bot{bot_token}"
    payload = {
        "chat_id": channel_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        if msg_id:
            edit_payload = dict(payload)
            edit_payload["message_id"] = msg_id
            response, data = post_telegram(f"{base_url}/editMessageText", edit_payload)
            if not response.ok:
                description = str(data.get("description", response.text))
                if "message is not modified" in description.lower():
                    print("Thông báo Telegram không thay đổi; bỏ qua cập nhật.")
                else:
                    print(f"Không thể sửa thông báo Telegram cũ; sẽ gửi thông báo mới. Lý do: {description}")
                    response, data = post_telegram(f"{base_url}/sendMessage", payload)
                    response.raise_for_status()
                    new_msg_id = data.get("result", {}).get("message_id")
                    if new_msg_id:
                        save_env("TELEGRAM_MSG_ID", str(new_msg_id))
            else:
                print("Đã cập nhật thông báo Telegram.")
        else:
            response, data = post_telegram(f"{base_url}/sendMessage", payload)
            response.raise_for_status()
            new_msg_id = data.get("result", {}).get("message_id")
            if new_msg_id:
                save_env("TELEGRAM_MSG_ID", str(new_msg_id))
                print(f"Đã lưu TELEGRAM_MSG_ID={new_msg_id} vào GITHUB_ENV.")
            print("Đã gửi thông báo Telegram.")

        if status in FINAL_STATUSES and builder_id:
            pm_title = {
                "success": "YÊU CẦU BUILD ROM CỦA BẠN ĐÃ HOÀN TẤT",
                "fail": "YÊU CẦU BUILD ROM CỦA BẠN BỊ LỖI",
                "cancelled": "YÊU CẦU BUILD ROM CỦA BẠN ĐÃ BỊ HỦY",
            }[status]
            pm_emoji = STATUS_EMOJI.get(status, "•")
            pm_lines = [f"{pm_emoji} <b>{escape(pm_title)}</b>", ""]
            pm_lines.extend(message.split("\n"))
            if status == "success":
                gdrive_link = read_gdrive_link()
                if is_available(gdrive_link):
                    pm_lines.extend(["", f"<b>Tải ROM (Google Drive):</b> <a href=\"{escape(gdrive_link)}\">Nhấn để tải</a>"])
                pm_lines.extend(["", "<b>Trang tải khác:</b> <a href=\"https://nothingsvn.vercel.app/\">nothingsvn.vercel.app</a>"])
            elif status == "fail":
                pm_lines.extend(["", "<b>Log lỗi:</b> file .txt sẽ được gửi riêng ngay sau tin nhắn này nếu tìm thấy log."])
            else:
                pm_lines.extend(["", "<b>Chi tiết:</b> mở Build log để xem lý do workflow bị hủy."])
            pm_text = clamp_message(pm_lines)
            pm_payload = {
                "chat_id": builder_id,
                "text": pm_text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            pm_response, pm_data = post_telegram(f"{base_url}/sendMessage", pm_payload)
            if pm_response.ok:
                print(f"Đã gửi tin nhắn riêng cho người dùng {builder_id}.")
            else:
                print(f"Không thể gửi tin nhắn riêng cho người dùng {builder_id}: {pm_data or pm_response.text}")

            if status == "fail" and os.environ.get("TELEGRAM_ERROR_LOG_SENT") != "1":
                if send_error_log_document(base_url, builder_id, status, repo_name, build_id):
                    os.environ["TELEGRAM_ERROR_LOG_SENT"] = "1"
                    save_env("TELEGRAM_ERROR_LOG_SENT", "1")
    except Exception as exc:
        print(f"Lỗi khi gửi/cập nhật thông báo Telegram: {exc}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Cách dùng: python notify.py <status> <repo_name> <rom_link> [prefix_id] [builder_name] [builder_id]")
        sys.exit(1)

    status_arg = sys.argv[1]
    repo_name_arg = sys.argv[2]
    rom_link_arg = sys.argv[3]
    prefix = sys.argv[4] if len(sys.argv) > 4 else "build"
    builder_name_arg = sys.argv[5] if len(sys.argv) > 5 else ""
    builder_id_arg = sys.argv[6] if len(sys.argv) > 6 else ""

    bot_token_arg = os.environ.get("TELEGRAM_BOT_TOKEN")
    channel_id_arg = os.environ.get("TELEGRAM_CHANNEL_ID")
    msg_id_arg = os.environ.get("TELEGRAM_MSG_ID")
    build_id_arg = os.environ.get("TELEGRAM_BUILD_ID")

    if not build_id_arg:
        random_digits = "".join(random.choices(string.digits, k=8))
        build_id_arg = f"{prefix}_{random_digits}"
        save_env("TELEGRAM_BUILD_ID", build_id_arg)

    write_file("bin/ddevice/telegram_build_id.txt", build_id_arg)

    if not bot_token_arg or not channel_id_arg:
        print("Lỗi: thiếu TELEGRAM_BOT_TOKEN hoặc TELEGRAM_CHANNEL_ID trong biến môi trường.")
        sys.exit(1)

    send_notification(
        status_arg,
        repo_name_arg,
        rom_link_arg,
        channel_id_arg,
        bot_token_arg,
        msg_id_arg,
        build_id_arg,
        builder_name_arg,
        builder_id_arg,
    )
