#!/usr/bin/env python3
import sys
import os

# Mật khẩu được sinh ngẫu nhiên khó giải mã (MD5/SHA256 style)
SECRET_KEY = "7f3c4d5e9a2b8f1c6e4d2a9b3c5f8e1a"

def fast_xor_chunk(file_path: str, key: str = SECRET_KEY, chunk_size: int = 50 * 1024 * 1024):
    """
    Hàm này dùng để Mã Hóa và Giải Mã (XOR 2 lần sẽ về trạng thái cũ).
    Chỉ xáo trộn 'chunk_size' byte đầu tiên của file để siêu tốc độ.
    """
    if not os.path.exists(file_path):
        print(f"[-] File not found: {file_path}")
        return

    key_bytes = key.encode('utf-8')
    
    with open(file_path, 'r+b') as f:
        data = f.read(chunk_size)
        actual_len = len(data)
        if actual_len == 0: 
            return
            
        # Tạo chuỗi khóa lặp lại cho vừa với dữ liệu
        repeats = actual_len // len(key_bytes) + 1
        keystream = (key_bytes * repeats)[:actual_len]
        
        # XOR siêu tốc bằng số nguyên (Big Int)
        int_data = int.from_bytes(data, 'little')
        int_key = int.from_bytes(keystream, 'little')
        encrypted = int_data ^ int_key
        
        # Ghi đè lại đúng phần đầu của file
        f.seek(0)
        f.write(encrypted.to_bytes(actual_len, 'little'))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python img_crypto.py <file1.img> [file2.img ...]")
        sys.exit(1)
        
    for path in sys.argv[1:]:
        fast_xor_chunk(path)
        print(f"[+] Processed: {path}")
