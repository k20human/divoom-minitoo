from flask import Flask, request, jsonify
import subprocess
import os
import json
import platform

app = Flask(__name__)

# Resolve the path to the 'dv' tool
HERE = os.path.dirname(os.path.abspath(__file__))
DV_PATH = os.path.abspath(os.path.join(HERE, "../../core/dv"))

def run_dv(args):
    """Helper to run the 'dv' command and capture output."""
    try:
        # We use 'oneshot' for API simplicity, but you can start a daemon
        # separately and the API will use it automatically via the FIFO.
        cmd = [DV_PATH] + args
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        return False, e.stderr

@app.route('/status', methods=['GET'])
def get_status():
    return jsonify({
        "status": "online",
        "platform": platform.system(),
        "dv_path": DV_PATH
    })

@app.route('/text', methods=['POST'])
def post_text():
    """Display scrolling text on the device."""
    data = request.json
    text = data.get('text', '')
    color = data.get('color', 'FFFFFF') # Hex color
    
    if not text:
        return jsonify({"error": "Missing 'text' parameter"}), 400

    # The MiniToo supports text via JSON commands (Channel/SetIndexText)
    # or via the ANCS notification path. For simplicity, we use the JSON command.
    payload = {
        "Command": "Device/SetText",
        "Text": text,
        "Color": f"#{color}"
    }
    
    success, output = run_dv(["json", json.dumps(payload)])
    if success:
        return jsonify({"message": "Text sent", "output": output})
    else:
        return jsonify({"error": output}), 500

@app.route('/face', methods=['POST'])
def post_face():
    """Switch to a specific face ID."""
    data = request.json
    face_id = data.get('id')
    
    if face_id is None:
        return jsonify({"error": "Missing 'id' parameter"}), 400
        
    success, output = run_dv(["face", str(face_id)])
    if success:
        return jsonify({"message": f"Switched to face {face_id}", "output": output})
    else:
        return jsonify({"error": output}), 500

@app.route('/brightness', methods=['POST'])
def post_brightness():
    """Set brightness (0-100)."""
    data = request.json
    level = data.get('level')
    
    if level is None:
        return jsonify({"error": "Missing 'level' parameter"}), 400
        
    success, output = run_dv(["brightness", str(level)])
    if success:
        return jsonify({"message": f"Brightness set to {level}%", "output": output})
    else:
        return jsonify({"error": output}), 500

@app.route('/raw', methods=['POST'])
def post_raw():
    """Send a raw hex payload."""
    data = request.json
    hex_data = data.get('hex', '')
    
    if not hex_data:
        return jsonify({"error": "Missing 'hex' parameter"}), 400
        
    success, output = run_dv(["raw"] + hex_data.split())
    if success:
        return jsonify({"message": "Raw command sent", "output": output})
    else:
        return jsonify({"error": output}), 500

@app.route('/json', methods=['POST'])
def post_json():
    """Send a custom Divoom JSON command."""
    data = request.json
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400
        
    success, output = run_dv(["json", json.dumps(data)])
    if success:
        return jsonify({"message": "JSON command sent", "output": output})
    else:
        return jsonify({"error": output}), 500

if __name__ == '__main__':
    # Default port 5000
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
