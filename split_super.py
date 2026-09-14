import os
import sys

# Thêm thư mục bin vào đường dẫn để import img_crypto
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bin'))
try:
    import img_crypto
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    print("Cảnh báo: Không tìm thấy bin/img_crypto.py, sẽ chỉ cắt file mà không mã hóa!")

def split_and_encrypt_file(input_file, chunk_size_mb):
    chunk_size = chunk_size_mb * 1024 * 1024
    if not os.path.exists(input_file):
        print(f"Lỗi: Không tìm thấy file {input_file}")
        return

    print(f"Đang cắt {input_file} thành các phần {chunk_size_mb}MB...")
    with open(input_file, 'rb') as f:
        chunk_num = 0
        while True:
            chunk_data = f.read(chunk_size)
            if not chunk_data:
                break
            
            output_file = f"{input_file}.{chunk_num:02d}"  # Đổi thành .00, .01 để dễ gộp
            with open(output_file, 'wb') as out_f:
                out_f.write(chunk_data)
            
            print(f"Đã tạo {output_file} ({len(chunk_data)} bytes)")
            
            # Mã hóa file sau khi cắt
            if HAS_CRYPTO:
                print(f"  -> Đang mã hóa {output_file}...")
                img_crypto.fast_xor_chunk(output_file)
                
            chunk_num += 1
            
    print("Hoàn tất cắt và mã hóa!")

if __name__ == "__main__":
    file_path = "build/baserom/images/super.img"
    size_mb = 800
    
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    if len(sys.argv) > 2:
        size_mb = int(sys.argv[2])
    
    split_and_encrypt_file(file_path, size_mb)


