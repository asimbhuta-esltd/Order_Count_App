from flask import Flask, render_template, request
from flask_socketio import SocketIO
import aiohttp, asyncio
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+ timezone support
import config

LOCAL_TZ = ZoneInfo("Europe/London")  # ← change to your local timezone

app = Flask(__name__)
socketio = SocketIO(app, async_mode='eventlet')

# In-memory totals
order_totals = {
    'processing': 0,
    'completed_today': 0,
    'orders_today': 0
}

# In-memory site-specific totals
site_totals = {site['name']: {'processing': 0, 'completed_today': 0} for site in config.SITES}


async def fetch_data(site, params):
    url = f"{site['url'].rstrip('/')}/wp-json/wc/v3/orders"
    auth = aiohttp.BasicAuth(site['consumer_key'], site['consumer_secret'])
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, auth=auth) as resp:
                data = await resp.json()
                headers = resp.headers
                return data, headers
    except Exception as e:
        print(f"Failed fetching data for {site['name']}: {e}")
        return [], {}

async def count_completed_today(orders):
    today = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    count = 0
    for o in orders or []:
        dc = o.get('date_completed')
        if dc and dc.startswith(today):
            count += 1
    return count

async def initial_fetch():
    """Fetch all sites, emit totals and per‑site data."""
    global order_totals
    now = datetime.now(LOCAL_TZ)
    today_str = now.strftime("%Y-%m-%d")
    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Fetching order stats...")

    tasks = []
    for site in config.SITES:
        tasks.append(fetch_data(site, {'status': 'processing', 'per_page': 1}))
        tasks.append(fetch_data(site, {'status': 'completed', 'per_page': 100}))
        tasks.append(fetch_data(site, {'after': f'{today_str}T00:00:00', 'per_page': 100}))  # today orders

    results = await asyncio.gather(*tasks)

    order_totals = {'processing': 0, 'completed_today': 0, 'orders_today': 0}
    idx = 0
    for site in config.SITES:
        proc_data, proc_headers = results[idx]; idx += 1
        comp_data, _ = results[idx]; idx += 1
        today_data, _ = results[idx]; idx += 1

        proc_count = int(proc_headers.get('X-Wp-Total', 0))
        comp_count = await count_completed_today(comp_data)
        today_count = len(today_data or [])

        order_totals['processing'] += proc_count
        order_totals['completed_today'] += comp_count
        order_totals['orders_today'] += today_count

        socketio.emit('site_data', {
            'name': site['name'],
            'url': site['url'],
            'processing': proc_count,
            'completed_today': comp_count,
            'orders_today': today_count
        })

    socketio.emit('totals', order_totals)

@socketio.on('connect')
def on_connect():
    socketio.start_background_task(lambda: asyncio.run(initial_fetch()))

@app.route('/')
def index():
    return render_template('dashboard.html', sites=config.SITES)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json or {}
    status = data.get('status', '')
    site_url = request.headers.get('X-Wc-Webhook-Source', '')

    if not site_url:
        return '', 400

    site = next((s for s in config.SITES if s['url'].rstrip('/') == site_url.rstrip('/')), None)
    if not site:
        return '', 404

    key = site['name']

    processing_delta = 0
    completed_delta = 0

    if status == 'processing':
        order_totals['processing'] += 1
        site_totals[key]['processing'] += 1
        processing_delta = 1
    elif status == 'completed':
        dc = data.get('date_completed', '')
        if dc.startswith(datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")):
            order_totals['completed_today'] += 1
            site_totals[key]['completed_today'] += 1
            completed_delta = 1

    socketio.emit('site_data', {
        'name': site['name'],
        'url': site['url'],
        'processing': site_totals[key]['processing'],
        'completed_today': site_totals[key]['completed_today']
    })

    socketio.emit('totals', order_totals)

    return '', 200

if __name__ == '__main__':
    import eventlet
    import eventlet.wsgi
    socketio.run(app, host='0.0.0.0', port=5001)
