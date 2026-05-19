"""一時スクリプト — 実行後に削除してください"""
import subprocess, os, glob
from pathlib import Path

base = Path(os.path.dirname(os.path.abspath(__file__)))
os.chdir(base)

# git ロックファイルをすべて削除
for lock in base.glob(".git/**/*.lock"):
    try:
        lock.unlink()
        print(f"✓ 削除: {lock.name}")
    except Exception as e:
        print(f"✗ 削除失敗: {lock.name} - {e}")

msg = (
    "feat: Google Drive API直接アップロード対応 + GDrive有効/無効の設定化\n\n"
    "GDriveストリーミングモードでshutil.copy2が機能しない問題を解消するため\n"
    "Google Drive APIを使った直接アップロード方式に切り替えた。\n"
    "また、GDriveを使わない運用にも対応できるよう設定フラグを追加した。\n\n"
    "新規: gdrive_uploader.py, setup_gdrive_auth.py\n"
    "変更: image_processor.py, config.py, requirements.txt, .env.example, .gitignore\n"
    "  - GDRIVE_UPLOAD_ENABLED フラグ追加（.envのfalseで完全無効化）\n"
    "  - credentials.json / token.json を .gitignore に追加"
)

subprocess.run(["git", "add", "-A"], check=True)
print("✓ ステージング完了")
result = subprocess.run(["git", "commit", "-m", msg])
print("コミット終了コード:", result.returncode)
if result.returncode == 0:
    result2 = subprocess.run(["git", "push", "origin", "main"])
    print("プッシュ終了コード:", result2.returncode)
