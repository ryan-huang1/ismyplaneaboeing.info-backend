from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import json
import re
import os
from datetime import datetime
import socket

app = Flask(__name__)
CORS(app)  # This enables CORS for all routes

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
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

def get_flight_info(flight_number, save_path='webpages'):
    def fetch_and_parse(flight_num):
        url = f"https://www.flightaware.com/live/flight/{flight_num}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"Failed to retrieve data. Status code: {response.status_code}")
            return None

        os.makedirs(save_path, exist_ok=True)
        with open(os.path.join(save_path, f"{flight_num}.html"), 'w', encoding='utf-8') as f:
            f.write(response.text)

        match = re.search(r'var trackpollBootstrap = ({.*?});', response.text, re.DOTALL)
        if not match:
            print("No flight data found in the response.")
            return None

        data = json.loads(match.group(1))
        return data.get('flights', {})

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

    def try_flight_number(flight_num):
        print(f"Attempting with flight number: {flight_num}")
        flights = fetch_and_parse(flight_num)
        return process_flight_info(flights), flight_num

    result, successful_flight_num = try_flight_number(flight_number)

    if not result:
        print("No valid data found. Trying with 'L' added.")
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
    print(f"Server is running on Local IP: {local_ip}")
    print(f"Server's Public IP: {public_ip}")
    app.run(host='0.0.0.0', debug=True)