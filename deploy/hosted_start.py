"""Accept a candidate on loopback before exposing Render's public port."""
import os
import subprocess
import sys
import time
import urllib.request


def main():
    env = os.environ.copy()
    env['APP_REVISION'] = env.get('RENDER_GIT_COMMIT') or env.get('APP_REVISION', 'hosted')
    subprocess.run([sys.executable, '-m', 'app.bootstrap_db'], env=env, check=True)
    warmup = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '10001', '--workers', '1', '--log-level', 'warning'], env=env)
    try:
        for _ in range(90):
            if warmup.poll() is not None:
                raise RuntimeError('Candidate API failed to start')
            try:
                with urllib.request.urlopen('http://127.0.0.1:10001/api/health', timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError('Candidate API startup timed out')
        subprocess.run([sys.executable, '/app/hosted_acceptance.py', '--base-url', 'http://127.0.0.1:10001', '--revision', env['APP_REVISION']], env=env, check=True, timeout=150)
    finally:
        warmup.terminate()
        try:
            warmup.wait(timeout=10)
        except subprocess.TimeoutExpired:
            warmup.kill()
            warmup.wait()
    os.environ.update(env)
    os.execv(sys.executable, [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', env.get('PORT', '10000'), '--workers', '1', '--proxy-headers', '--forwarded-allow-ips', '*'])


if __name__ == '__main__':
    main()
