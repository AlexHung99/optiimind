"""Apply pending updates before starting the desktop application."""
from pathlib import Path
import subprocess
import sys
import tempfile

from opti_update import UPDATE_DIR, app_running, apply_pending


def install_requirements(data):
    with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as stream:
        stream.write(data)
        path = Path(stream.name)
    try:
        python = Path(sys.executable).with_name('python.exe')
        result = subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(path)],
            capture_output=True, timeout=600, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError('新版相依套件安裝失敗，保留目前版本。')
    finally:
        path.unlink(missing_ok=True)


def main():
    root = Path(__file__).resolve().parent
    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    # Serialize launchers; never replace files while the chat application is alive.
    import msvcrt
    with (UPDATE_DIR/'launch.lock').open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        try:
            if not app_running():
                try:
                    apply_pending(root, installer=install_requirements)
                    (UPDATE_DIR/'last-error.txt').unlink(missing_ok=True)
                except Exception as error:
                    (UPDATE_DIR/'last-error.txt').write_text(str(error), encoding='utf-8')
                from opti_setup import dependencies_ready, run_setup
                if not dependencies_ready() and not run_setup():
                    return
            subprocess.Popen([sys.executable, str(root/'opti_app.py')], cwd=root, creationflags=subprocess.CREATE_NO_WINDOW)
            # Keep a second launcher from updating files before the new app claims its mutex.
            import time
            for _ in range(50):
                if app_running():
                    break
                time.sleep(.1)
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


if __name__ == '__main__':
    main()
