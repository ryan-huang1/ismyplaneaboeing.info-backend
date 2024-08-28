import os
import signal
import sys
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import json
import re
from datetime import datetime
import socket
from dotenv import load_dotenv
import random

# Load environment variables
load_dotenv()
ORDER_TOKEN = os.getenv('ORDER_TOKEN')
PROXY_KEY = os.getenv('PROXY_KEY')

# Set the port for the Flask app
PORT = 5001

app = Flask(__name__)
CORS(app)  # This enables CORS for all routes

# List of user agents to rotate
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Edg/91.0.864.59',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36'
]

# Signal handler function
def signal_handler(sig, frame):
    print('\nShutting down the server gracefully...')
    sys.exit(0)

# Register the signal handler
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def get_public_ip():
    try:
        response = requests.get('https://api.ipify.org')
        return response.text
    except:
        return "Unable to get public IP"

def fetch_proxies():
    url = "https://api.oculusproxies.com/v1/configure/proxy/getProxies"
    payload = json.dumps({
        "orderToken": ORDER_TOKEN,
        "country": "US",
        "numberOfProxies": 1000,  # Requesting 1000 proxies
        "whiteListIP": [get_local_ip()],
        "enableSock5": False,
        "planType": "SHARED_DC",
    })
    headers = {
        'authToken': PROXY_KEY,
        'Content-Type': 'application/json'
    }
    response = requests.post(url, headers=headers, data=payload)
    proxies = response.json()

    print(f"Fetched {len(proxies)} proxies")
    return proxies

def parse_proxy(proxy_string):
    parts = proxy_string.split(':')
    return {
        'proxy_address': parts[0],
        'port': parts[1],
        'username': parts[2],
        'password': parts[3]
    }

# Fetch and parse proxies, store in memory
proxies = [parse_proxy(proxy) for proxy in fetch_proxies()]

def get_flight_info(flight_number):
    def fetch_and_parse(flight_num, proxy, user_agent):
        url = f"https://www.flightaware.com/live/flight/{flight_num}"
        headers = {'User-Agent': user_agent}

        proxy_url = f"http://{proxy['username']}:{proxy['password']}@{proxy['proxy_address']}:{proxy['port']}"
        proxies_dict = {'http': proxy_url, 'https': proxy_url}

        try:
            response = requests.get(url, headers=headers, proxies=proxies_dict, timeout=10)
            if response.status_code != 200:
                print(f"Failed to retrieve data. Status code: {response.status_code}")
                return None

            match = re.search(r'var trackpollBootstrap = ({.*?});', response.text, re.DOTALL)
            if not match:
                print("No flight data found in the response.")
                return None

            data = json.loads(match.group(1))
            return data.get('flights', {})
        except requests.RequestException as e:
            print(f"Request failed: {e}")
            return None

    def process_flight_info(flights):
        if not flights:
            print("No valid flight data found.")
            return None

        flight_info = next(iter(flights.values()))

        def format_time(timestamp):
            return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S') if timestamp else "N/A"

        result = {
            'aircraft': {
                'friendly_type': flight_info.get('aircraft', {}).get('friendlyType', 'N/A'),
                'aircraft_type': flight_info.get('aircraft', {}).get('type', 'N/A')
            },
            'origin': {
                'code': flight_info.get('origin', {}).get('icao', 'N/A'),
                'airport': flight_info.get('origin', {}).get('friendlyName', 'N/A'),
                'city': flight_info.get('origin', {}).get('friendlyLocation', 'N/A')
            },
            'destination': {
                'code': flight_info.get('destination', {}).get('icao', 'N/A'),
                'airport': flight_info.get('destination', {}).get('friendlyName', 'N/A'),
                'city': flight_info.get('destination', {}).get('friendlyLocation', 'N/A')
            },
            'flight_status': flight_info.get('flightStatus', 'N/A'),
            'departure': {
                'scheduled': format_time(flight_info.get('gateDepartureTimes', {}).get('scheduled')),
                'actual': format_time(flight_info.get('gateDepartureTimes', {}).get('actual')),
                'estimated': format_time(flight_info.get('gateDepartureTimes', {}).get('estimated'))
            },
            'arrival': {
                'scheduled': format_time(flight_info.get('gateArrivalTimes', {}).get('scheduled')),
                'actual': format_time(flight_info.get('gateArrivalTimes', {}).get('actual')),
                'estimated': format_time(flight_info.get('gateArrivalTimes', {}).get('estimated'))
            },
            'flight_duration': f"{flight_info.get('flightPlan', {}).get('ete', 0) // 60} minutes",
            'route': flight_info.get('flightPlan', {}).get('route', 'N/A')
        }

        if any(v != 'N/A' and v != '0 minutes' for k, v in result.items() if not isinstance(v, dict)) or \
           any(v != 'N/A' for d in result.values() if isinstance(d, dict) for v in d.values()):
            return result
        else:
            print("All retrieved data is 'N/A' or '0 minutes'.")
            return None

    def try_flight_number(flight_num, max_attempts=5):
        used_proxy_addresses = set()
        for attempt in range(max_attempts):
            print(f"Attempt {attempt + 1} with flight number: {flight_num}")
            
            # Select a proxy that hasn't been used yet
            available_proxies = [p for p in proxies if p['proxy_address'] not in used_proxy_addresses]
            if not available_proxies:
                print("All proxies have been used. Resetting proxy list.")
                used_proxy_addresses.clear()
                available_proxies = proxies
            
            proxy = random.choice(available_proxies)
            used_proxy_addresses.add(proxy['proxy_address'])
            
            # Select a random user agent
            user_agent = random.choice(USER_AGENTS)
            
            flights = fetch_and_parse(flight_num, proxy, user_agent)
            if flights:
                result = process_flight_info(flights)
                if result:
                    return result, flight_num
        return None, None

    result, successful_flight_num = try_flight_number(flight_number)

    if not result:
        print("No valid data found after multiple attempts. Trying with 'L' added.")
        match = re.match(r'^([A-Z]+)(\d+)$', flight_number)
        if match:
            modified_flight_number = f"{match.group(1)}L{match.group(2)}"
            result, successful_flight_num = try_flight_number(modified_flight_number)

    if result:
        print(f"Flight information found using flight number: {successful_flight_num}")
        return result, successful_flight_num
    else:
        return {"error": "Flight information not found or could not be processed."}, None

@app.route('/flight_info', methods=['GET'])
def flight_info():
    flight_number = request.args.get('flight_number')
    if not flight_number:
        return jsonify({"error": "Flight number is required"}), 400

    flight_info, successful_flight_num = get_flight_info(flight_number)

    if "error" not in flight_info:
        return jsonify({
            "flight_number": successful_flight_num,
            "flight_info": flight_info
        })
    else:
        return jsonify(flight_info), 404

if __name__ == '__main__':
    local_ip = get_local_ip()
    public_ip = get_public_ip()
    print(f"Server is starting...")
    print(f"Local IP: {local_ip}")
    print(f"Public IP: {public_ip}")
    print(f"Fetched {len(proxies)} proxies")
    print(f"Server is running on port: {PORT}")
    app.run(host='0.0.0.0', port=80, debug=True)