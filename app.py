from flask import Flask, render_template, request
from flask_socketio import SocketIO
import aiohttp, asyncio
from datetime import datetime
import config

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

# ... (existing functions)

@app.route('/')
def index():
    """Render the dashboard template and pass the current time."""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Current time: {current_time}")  # Debugging print statement
    return render_template('dashboard.html', sites=config.SITES, current_time=current_time)


# In-memory site-specific totals
site_totals = {site['name']: {'processing': 0, 'completed_today': 0} for site in config.SITES}

async def fetch_data(site, params):
    """Fetch data from WooCommerce API."""
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
    """Count the completed orders created today."""
    today = datetime.now().strftime("%Y-%m-%d")
    count = 0
    for order in orders or []:
        dc = order.get('date_completed')
        if dc and dc.startswith(today):  # Ensure date_completed matches today's date
            count += 1
    return count

async def count_orders_today(orders):
    """Count all orders created today, regardless of their status."""
    today = datetime.now().strftime("%Y-%m-%d")
    count = 0
    for order in orders or []:
        dc = order.get('date_created')
        if dc and dc.startswith(today):  # Ensure date_created matches today's date
            count += 1
    return count

async def initial_fetch():
    """Fetch all sites, emit totals and per-site data."""
    global order_totals
    today = datetime.now().strftime("%Y-%m-%d")
    tasks = []
    
    for site in config.SITES:
        # Fetch completed and paid orders created today (filter by status and payment)
        tasks.append(fetch_data(site, {
            'status': 'completed',
            'payment_status': 'paid',
            'after': f'{today}T00:00:00',  # Only orders created today
            'per_page': 100
        }))
        # Fetch all processing orders, regardless of date
        tasks.append(fetch_data(site, {
            'status': 'processing',
            'payment_status': 'paid',
            'per_page': 100
        }))
    
    results = await asyncio.gather(*tasks)

    order_totals = {'processing': 0, 'completed_today': 0, 'orders_today': 0}
    idx = 0
    for site in config.SITES:
        # Unpack results for completed and processing orders
        completed_data, _ = results[idx]; idx += 1
        processing_data, _ = results[idx]; idx += 1
        
        # Count the number of completed orders today
        completed_today_count = await count_completed_today(completed_data)
        # Count all processing orders regardless of the date
        processing_count = len(processing_data or [])
        # Count all orders created today, regardless of status
        orders_today_count = await count_orders_today(completed_data + processing_data)

        # Update the totals for today
        order_totals['completed_today'] += completed_today_count
        order_totals['processing'] += processing_count
        order_totals['orders_today'] += orders_today_count  # Total orders today

        # Emit updated per-site data
        socketio.emit('site_data', {
            'name': site['name'],
            'url': site['url'],
            'processing': processing_count,
            'completed_today': completed_today_count,
            'orders_today': orders_today_count
        })

    # Emit global totals
    socketio.emit('totals', order_totals)

@socketio.on('connect')
def on_connect():
    socketio.start_background_task(lambda: asyncio.run(initial_fetch()))

@app.route('/')
def index():
    """Render the dashboard template."""
    return render_template('dashboard.html', sites=config.SITES)

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle WooCommerce webhooks."""
    data = request.json or {}
    status = data.get('status', '')
    site_url = request.headers.get('X-Wc-Webhook-Source', '')  # WooCommerce sends this header

    if not site_url:
        return '', 400  # We need this to identify which site sent it

    # Find the site from config.SITES based on the URL
    site = next((s for s in config.SITES if s['url'].rstrip('/') == site_url.rstrip('/')), None)
    if not site:
        return '', 404  # Unknown site

    key = site['name']  # for matching config.SITES

    # Find and emit site-specific updates
    processing_delta = 0
    completed_delta = 0

    if status == 'processing':
        order_totals['processing'] += 1
        site_totals[key]['processing'] += 1  # Update site-specific totals
        processing_delta = 1
    elif status == 'completed':
        dc = data.get('date_completed', '')
        if dc.startswith(datetime.now().strftime("%Y-%m-%d")):
            order_totals['completed_today'] += 1
            site_totals[key]['completed_today'] += 1  # Update site-specific totals
            completed_delta = 1
    
    # Emit updated per-site data
    socketio.emit('site_data', {
        'name': site['name'],
        'url': site['url'],
        'processing': site_totals[key]['processing'],
        'completed_today': site_totals[key]['completed_today']
    })

    # Emit updated totals
    socketio.emit('totals', order_totals)

    return '', 200

if __name__ == '__main__':
    import eventlet
    import eventlet.wsgi
    socketio.run(app, host='0.0.0.0', port=5001)
