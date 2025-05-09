import browser_cookie3
import http.cookiejar

def save_instagram_cookies(output_file="cookies.txt", domain="instagram.com"):
    # Ambil cookies dari browser yang aktif (Chrome default)
    cj = browser_cookie3.load(domain_name=domain)

    # Simpan dalam format Netscape yang kompatibel dengan yt-dlp
    with open(output_file, "w") as f:
        f.write("# Netscape HTTP Cookie File\n")
        for cookie in cj:
            if domain in cookie.domain:
                f.write(
                    f"{cookie.domain}\t"
                    f"{str(cookie.domain.startswith('.')).lower()}\t"
                    f"{cookie.path}\t"
                    f"{str(cookie.secure).upper()}\t"
                    f"{cookie.expires if cookie.expires else 0}\t"
                    f"{cookie.name}\t"
                    f"{cookie.value}\n"
                )

    print(f"✅ Cookies Instagram berhasil disimpan ke {output_file}")

if __name__ == "__main__":
    save_instagram_cookies()
