"""Start cloudflared tunnel, capture URL, register webhook with Shopee."""
import subprocess, re, sys, time, json, os

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.getcwd())

proc = subprocess.Popen(
    ['cloudflared.exe', 'tunnel', '--url', 'http://127.0.0.1:8766', '--no-autoupdate'],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, bufsize=1,
)

pattern = re.compile(r'https://[a-zA-Z0-9.-]+\.trycloudflare\.com')
tunnel_url = None
deadline = time.time() + 45

while time.time() < deadline:
    line = proc.stdout.readline()
    if not line:
        break
    line = line.strip()
    if line:
        print(f'[cloudflared] {line}')
    m = pattern.search(line)
    if m:
        tunnel_url = m.group(0)
        break

if tunnel_url:
    callback = f'{tunnel_url}/webhook/shopee'
    print(f'\nTUNNEL_URL={tunnel_url}')
    print(f'CALLBACK_URL={callback}')

    with open('reports/laura_webhook_tunnel_latest.txt', 'w') as f:
        f.write(tunnel_url + '\n')
    with open('reports/laura_webhook_callback_latest.txt', 'w') as f:
        f.write(callback + '\n')

    from shopee_agent.shopee_webhook import register_webhook
    result = register_webhook(webhook_url=callback)
    print(f'\nREGISTER_RESULT={json.dumps(result, ensure_ascii=False)}')

    print('\nTunnel running. Press Ctrl+C to stop...')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
else:
    print('ERROR: No tunnel URL found within 45s')
    # Show last lines of output
    try:
        proc.terminate()
    except Exception:
        pass
