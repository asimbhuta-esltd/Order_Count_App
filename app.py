from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
import aiohttp, asyncio
from datetime import datetime, timedelta
import pytz
import config
import json

app = Flask(__name__)
socketio = SocketIO(app, async_mode='eventlet')

# In-memory totals
order_totals = {
    'processing': 0,
    'completed_today': 0,
    'orders_today': 0,
    'orders_yesterday': 0
}

# In-memory site-specific totals
site_totals = {site['name']: {'processing': 0, 'completed_today': 0, 'orders_today': 0, 'orders_yesterday': 0} for site in config.SITES}

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
    today = datetime.now(pytz.timezone('Europe/London')).strftime("%Y-%m-%d")
    count = 0
    for o in orders or []:
        dc = o.get('date_completed')
        if dc and dc.startswith(today):
            count += 1
    return count

async def count_orders_today(orders):
    today = datetime.now(pytz.timezone('Europe/London')).strftime("%Y-%m-%d")
    count = 0
    for o in orders or []:
        dc = o.get('date_created')
        status = o.get('status', '')
        if dc and dc.startswith(today) and status not in ['cancelled', 'pending']:
            count += 1
    return count

async def count_orders_yesterday(orders):
    yesterday = (datetime.now(pytz.timezone('Europe/London')) - timedelta(days=1)).strftime("%Y-%m-%d")
    count = 0
    for o in orders or []:
        dc = o.get('date_created')
        status = o.get('status', '')
        if dc and dc.startswith(yesterday) and status not in ['cancelled', 'pending']:
            count += 1
    return count

async def initial_fetch():
    global order_totals
    today = datetime.now(pytz.timezone('Europe/London')).strftime("%Y-%m-%d")
    yesterday = (datetime.now(pytz.timezone('Europe/London')) - timedelta(days=1)).strftime("%Y-%m-%d")
    tasks = []
    for site in config.SITES:
        tasks.append(fetch_data(site, {'status': 'processing', 'per_page': 1}))
        tasks.append(fetch_data(site, {'status': 'completed', 'per_page': 100}))
        tasks.append(fetch_data(site, {'after': f'{today}T00:00:00', 'per_page': 100}))
        tasks.append(fetch_data(site, {'after': f'{yesterday}T00:00:00', 'per_page': 100}))
    results = await asyncio.gather(*tasks)

    order_totals = {'processing': 0, 'completed_today': 0, 'orders_today': 0, 'orders_yesterday': 0}
    idx = 0
    for site in config.SITES:
        proc_data, proc_headers = results[idx]; idx += 1
        comp_data, _ = results[idx]; idx += 1
        today_data, _ = results[idx]; idx += 1
        yesterday_data, _ = results[idx]; idx += 1

        proc_count = int(proc_headers.get('X-Wp-Total', 0))
        comp_count = await count_completed_today(comp_data)
        today_count = await count_orders_today(today_data)
        yesterday_count = await count_orders_yesterday(yesterday_data)

        order_totals['processing'] += proc_count
        order_totals['completed_today'] += comp_count
        order_totals['orders_today'] += today_count
        order_totals['orders_yesterday'] += yesterday_count

        site_totals[site['name']]['processing'] = proc_count
        site_totals[site['name']]['completed_today'] = comp_count
        site_totals[site['name']]['orders_today'] = today_count
        site_totals[site['name']]['orders_yesterday'] = yesterday_count

        socketio.emit('site_data', {
            'name': site['name'],
            'url': site['url'],
            'processing': proc_count,
            'completed_today': comp_count,
            'orders_today': today_count,
            'orders_yesterday': yesterday_count
        })

    socketio.emit('totals', order_totals)

@app.route('/fetch_data')
def fetch_data_button():
    # Trigger data fetch when the button is clicked
    asyncio.run(initial_fetch())
    return jsonify({'status': 'success', 'message': 'Data fetched successfully'})

@socketio.on('connect')
def on_connect():
    socketio.start_background_task(lambda: asyncio.run(initial_fetch()))

@app.route('/')
def index():
    current_time = datetime.now(pytz.timezone('Europe/London')).strftime('%Y-%m-%d %H:%M:%S')
    return render_template('dashboard.html', sites=config.SITES, current_time=current_time)

# Webhook route to handle order updates
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        print(f"Webhook received: {data}")
        # Assuming the payload includes the order status change
        order_id = data.get('id')
        status = data.get('status')
        
        # Update in-memory totals based on the new order status
        for site in config.SITES:
            if site['name'] in data.get('site', ''):
                if status == 'completed':
                    site_totals[site['name']]['completed_today'] += 1
                    order_totals['completed_today'] += 1
                elif status == 'processing':
                    site_totals[site['name']]['processing'] += 1
                    order_totals['processing'] += 1
                elif status in ['cancelled', 'pending']:
                    # Adjust the totals if the order is cancelled or pending
                    pass
                
                # Emit updated totals to the client
                socketio.emit('site_data', site_totals[site['name']])
                socketio.emit('totals', order_totals)
                break
    except Exception as e:
        print(f"Error handling webhook: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to process webhook'}), 500

    return jsonify({'status': 'success', 'message': 'Webhook processed successfully'}), 200

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5001)
