#!/usr/bin/env python3
import subprocess
import sys
import os
import re
import json
import threading
import queue
import time
import shutil
from urllib.parse import quote, unquote

# -----------------------------
# Auto-install missing packages
# -----------------------------
required_packages = ["flask", "yt-dlp", "requests", "pcloud"]
try:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            print(f"⚡ Installing missing package: {package} ...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])
except Exception as e:
    print(f"Error installing packages: {e}")
    sys.exit(1)

from flask import Flask, render_template_string, request, send_from_directory, flash, url_for, Response, redirect, session, jsonify
from werkzeug.utils import secure_filename
import requests
import yt_dlp
from pcloud import PyCloud

# -----------------------------
# Configuration
# -----------------------------
FLASK_PORT = 5000
DOWNLOAD_FOLDER = os.path.join(os.getcwd(), "downloads")
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

COOKIES_FILE = os.path.join(os.getcwd(), "youtube_cookies.txt")
PIXELDRAIN_API_KEY = "eb6f7009-6a28-41ef-bbd3-a17f37d026c1"  # Replace with your key if you have one

# pCloud Configuration
PCLOUD_EMAIL = "moh.aziz.8890@gmail.com"
PCLOUD_PASSWORD = "Oga123456?!" # Note: Storing passwords in code is not secure for production
PCLOUD_FOLDER = "downloader"
PCLOUD_TOKEN_FILE = os.path.join(os.getcwd(), "pcloud_token.json") # Token file for auth

print(f"📂 Downloads folder: {os.path.abspath(DOWNLOAD_FOLDER)}")
print(f"🍪 Cookies file: {'Exists' if os.path.exists(COOKIES_FILE) else 'Not found'}")

# -----------------------------
# Flask & SSE Setup
# -----------------------------
app = Flask(__name__)
app.secret_key = "a_very_secret_key_for_flask"
progress_queue = queue.Queue()

# -----------------------------
# HTML Template (with CSS & JavaScript)
# -----------------------------
TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Video Downloader</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; background-color: #f4f4f9; color: #333; margin: 0; padding: 20px; }
        .container { max-width: 800px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1, h2, h3 { color: #444; }
        hr { border: 0; border-top: 1px solid #ddd; margin: 20px 0; }
        input[type="text"], input[type="number"], select { width: 100%; padding: 8px; margin: 5px 0 15px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
        input[type="file"] { margin-bottom: 15px; }
        button { background-color: #007bff; color: white; padding: 10px 15px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; margin-right: 5px; }
        button:hover { background-color: #0056b3; }
        button.delete { background-color: #dc3545; }
        button.delete:hover { background-color: #c82333; }
        button.upload { background-color: #17a2b8; }
        button.upload:hover { background-color: #138496; }
        button.pcloud { background-color: #8E44AD; }
        button.pcloud:hover { background-color: #732d91; }
        button.encode { background-color: #28a745; }
        button.encode:hover { background-color: #218838; }
        button.rename { background-color: #ffc107; color: #212529; }
        button.rename:hover { background-color: #e0a800; }
        a { color: #007bff; text-decoration: none; }
        a:hover { text-decoration: underline; }
        pre { background-color: #eee; padding: 10px; border-radius: 4px; white-space: pre-wrap; word-wrap: break-word; }
        .flash-msg { padding: 10px; border-radius: 4px; margin-bottom: 15px; }
        .flash-success { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .flash-error { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .flash-info { background-color: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        .progress-container { display: none; margin-top: 20px; }
        .progress-bar { width: 100%; background-color: #e9ecef; border-radius: 4px; }
        .progress-bar-inner { width: 0%; height: 24px; background-color: #28a745; text-align: center; line-height: 24px; color: white; border-radius: 4px; transition: width 0.4s ease; }
        #progress-log { margin-top: 10px; font-family: monospace; font-size: 12px; max-height: 200px; overflow-y: auto; background: #333; color: #fff; padding: 10px; border-radius: 4px; }
        .notification { position: fixed; top: 20px; right: 20px; padding: 15px 20px; border-radius: 8px; color: white; font-weight: bold; z-index: 10000; animation: slideIn 0.3s ease-out; }
        .notification.success { background-color: #28a745; }
        .notification.error { background-color: #dc3545; }
        .notification.info { background-color: #17a2b8; }
        @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
    </style>
</head>
<body>
<div class="container">
    <h1>Video Downloader & Uploader</h1>
    <p>Powered by yt-dlp, FFmpeg, Pixeldrain & pCloud</p>
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="flash-msg flash-{{ category }}">{{ message|safe }}</div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div id="progress-container" class="progress-container">
        <h3 id="progress-stage">Starting...</h3>
        <div class="progress-bar">
            <div id="progress-bar-inner" class="progress-bar-inner">0%</div>
        </div>
        <pre id="progress-log"></pre>
    </div>

    <!-- MANUAL MERGE SECTION -->
    <hr>
    <h2>Manual Format Merge</h2>
    <p>Fetch formats from a URL, then manually provide the Video and Audio IDs to merge into an MKV file.</p>
    <form method="POST" action="{{ url_for('index') }}">
        <label>Page URL:</label><br>
        <input type="text" name="manual_url" size="80" value="{{ manual_url }}" required><br>
        <button type="submit" name="action" value="manual_fetch">Fetch Formats</button><br><br>

        {% if manual_formats_raw %}
            <input type="hidden" name="manual_url" value="{{ manual_url }}">
            <h3>Available Formats (Raw):</h3>
            <pre>{{ manual_formats_raw }}</pre>

            <label>Video ID:</label><br>
            <input type="text" name="manual_video_id" required placeholder="Enter the ID of the video stream"><br>

            <label>Audio ID (optional):</label><br>
            <input type="text" name="manual_audio_id" placeholder="Enter ID of audio stream (leave blank for video-only)"><br>
            
            <label>Filename (will be saved as .mkv):</label><br>
            <input type="text" name="manual_filename" value="{{ manual_filename }}" required><br><br>
            
            <button type="submit" name="action" value="manual_merge">Merge & Download</button>
        {% endif %}
    </form>
    <hr>

    <h2>Advanced Download</h2>
    <form method="POST" action="{{ url_for('index') }}" id="download-form" onsubmit="return validateForm()">
        <label>Video URL:</label><br>
        <input type="text" name="url" size="80" value="{{ url }}" required><br>
        <button type="submit" name="action" value="fetch">Fetch Formats</button><br><br>

        {% if formats %}
            <input type="hidden" name="url" value="{{ url }}">
            
            <label>Video Format:</label><br>
            <select name="video_id" required>
                {% for format in video_formats %}
                    <option value="{{ format.id }}" {% if format.is_muxed %}style="font-style: italic;"{% endif %}>{{ format.display }}{% if format.is_muxed %} (with audio){% endif %}</option>
                {% endfor %}
            </select><br>

            <label>Audio Format (optional):</label><br>
            <select name="audio_id">
                <option value="">Best Audio (default)</option>
                {% for format in audio_formats %}
                    <option value="{{ format.id }}">{{ format.display }}</option>
                {% endfor %}
            </select><br>
            
            <label>Filename:</label><br>
            <input type="text" name="filename" value="{{ original_name }}" required><br>
            <label>Codec:</label><br>
            <select name="codec" id="codec" required>
                <option value="none" {% if codec == "none" %}selected{% endif %}>No Encoding</option>
                <option value="h265" {% if codec == "h265" %}selected{% endif %}>Encode to H.265 (x265)</option>
                <option value="av1" {% if codec == "av1" %}selected{% endif %}>Encode to AV1 (SVT-AV1)</option>
            </select><br>
            <div id="encoding-options" style="display: {% if codec != 'none' %}block{% else %}none{% endif %};">
                <label>Encoding Mode:</label><br>
                <select name="pass_mode" id="pass_mode" required>
                    <option value="1-pass" {% if pass_mode == "1-pass" %}selected{% endif %}>1-pass (CRF)</option>
                    <option value="2-pass" {% if pass_mode == "2-pass" %}selected{% endif %}>2-pass (VBR)</option>
                </select><br>
                <label>Preset (slower = better quality/smaller file):</label><br>
                <select name="preset" id="preset"></select><br>

                <label>Video Bitrate (kb/s, optional):</label><br>
                <input type="number" name="bitrate" id="bitrate" value="{{ bitrate }}" min="100" placeholder="e.g., 2000 for 2 Mbps (leave empty for default)"><br>

                <label>CRF (0–63, lower = better quality):</label><br>
                <input type="number" name="crf" id="crf" value="{{ crf|default(28 if codec == 'h265' else 35) }}" min="0" max="63" step="1" placeholder="e.g., 28 for H.265, 35 for AV1"><br>

                <label>Audio Bitrate (kb/s):</label><br>
                <input type="number" name="audio_bitrate" id="audio_bitrate" value="{{ audio_bitrate|default('96') }}" min="32" max="512" step="8" placeholder="e.g., 64, 96, 128"><br>

                <label>Frame Rate (optional):</label><br>
                <select name="fps">
                    <option value="">Original</option>
                    <option value="24">24 fps</option>
                    <option value="30">30 fps</option>
                    <option value="60">60 fps</option>
                </select><br>

                <label><input type="checkbox" name="force_stereo" value="true"> Force Stereo (2-channel) Audio</label><br>
            </div>
            <script>
                const codecSelect = document.getElementById('codec');
                const presetSelect = document.getElementById('preset');
                const crfInput = document.getElementById('crf');
                const passModeSelect = document.getElementById('pass_mode');
                const bitrateInput = document.getElementById('bitrate');

                function updatePresetOptions() {
                    const codec = codecSelect.value;
                    presetSelect.innerHTML = '';
                    if (codec === 'av1') {
                        for (let p = 0; p <= 13; p++) {
                            let label = p.toString();
                            if (p === 0) label += ' (slowest)';
                            else if (p === 13) label += ' (fastest)';
                            else if (p > 7) label += ' (fast)';
                            else label += ' (medium)';
                            const option = document.createElement('option');
                            option.value = p;
                            option.text = label;
                            if (p === 6) option.selected = true;
                            presetSelect.appendChild(option);
                        }
                        crfInput.value = crfInput.value || '35';
                        crfInput.placeholder = 'e.g., 35 for AV1';
                    } else if (codec === 'h265') {
                        const presets = ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow', 'placebo'];
                        presets.forEach(p => {
                            const option = document.createElement('option');
                            option.value = p;
                            option.text = p;
                            if (p === 'faster') option.selected = true;
                            presetSelect.appendChild(option);
                        });
                        crfInput.value = crfInput.value || '28';
                        crfInput.placeholder = 'e.g., 28 for H.265';
                    }
                    const encodingOptions = document.getElementById('encoding-options');
                    encodingOptions.style.display = codec !== 'none' ? 'block' : 'none';
                    
                    if (codec === 'none') {
                        bitrateInput.removeAttribute('required');
                        bitrateInput.removeAttribute('min');
                        bitrateInput.value = '';
                    } else {
                        bitrateInput.setAttribute('min', '100');
                        if (passModeSelect.value === '2-pass') {
                            bitrateInput.setAttribute('required', 'required');
                        } else {
                            bitrateInput.removeAttribute('required');
                        }
                    }
                }

                function validateForm() {
                    const codec = codecSelect.value;
                    if (codec !== 'none') {
                        if (!presetSelect.value) {
                            alert('Please select a preset.');
                            return false;
                        }
                        if (passModeSelect.value === '2-pass' && (!bitrateInput.value || parseInt(bitrateInput.value) < 100)) {
                            alert('Please specify a valid video bitrate (minimum 100) for 2-pass encoding.');
                            return false;
                        }
                    }
                    return true;
                }

                codecSelect.addEventListener('change', updatePresetOptions);
                passModeSelect.addEventListener('change', function() {
                    if (codecSelect.value !== 'none') {
                        if (this.value === '2-pass') {
                            bitrateInput.setAttribute('required', 'required');
                        } else {
                            bitrateInput.removeAttribute('required');
                        }
                    }
                });

                document.addEventListener('DOMContentLoaded', updatePresetOptions);
            </script>
            <br>
            <label><input type="checkbox" name="upload_pixeldrain" value="true"> Upload to Pixeldrain after completion</label><br>
            <label><input type="checkbox" name="upload_pcloud" value="true"> Upload to pCloud after completion</label><br><br>
            <button type="submit" name="action" value="download">Download & Convert</button>
            <h3>Available Formats (Raw):</h3>
            <pre>{{ formats }}</pre>
        {% endif %}
    </form>
    
    <hr>
    
    <h2>Direct URL Download</h2>
    <form method="POST" action="{{ url_for('index') }}">
        <label>URL (Video, Playlist, or any direct file):</label><br>
        <input type="text" name="direct_url" size="80" required><br>
        <label><input type="checkbox" name="upload_pixeldrain_direct" value="true"> Upload to Pixeldrain after download</label><br>
        <label><input type="checkbox" name="upload_pcloud_direct" value="true"> Upload to pCloud after download</label><br>
        <button type="submit" name="action" value="direct_download">Download to Server</button>
        <button type="submit" name="action" value="direct_upload_pixeldrain" class="upload">Upload to Pixeldrain</button>
        <button type="submit" name="action" value="direct_upload_pcloud" class="pcloud">Upload to pCloud</button>
    </form>

    <hr>

    <h2>Upload File</h2>
    <form method="POST" action="{{ url_for('upload_direct') }}" enctype="multipart/form-data">
        <label>Select a file from your computer to upload to Pixeldrain:</label><br>
        <input type="file" name="file" required><br>
        <button type="submit" class="upload">Upload to Pixeldrain</button>
    </form>

    <hr>
    <p><a href="{{ url_for('list_files') }}">📂 Manage Downloaded Files</a></p>
</div>

<script>
    function showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.textContent = message;
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.style.opacity = '0';
            setTimeout(() => {
                document.body.removeChild(notification);
            }, 300);
        }, 3000);
    }

    document.addEventListener("DOMContentLoaded", function() {
        {% if download_started %}
            const progressContainer = document.getElementById('progress-container');
            const stage = document.getElementById('progress-stage');
            const progressBar = document.getElementById('progress-bar-inner');
            const log = document.getElementById('progress-log');
            
            progressContainer.style.display = 'block';

            const eventSource = new EventSource("{{ url_for('progress_stream') }}");
            let finalUrl = null; // Variable to store the final URL from the upload
            
            eventSource.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);
                    
                    if (data.final_url) {
                        finalUrl = data.final_url;
                    }
                    
                    if (data.log && data.log === 'DONE') {
                        eventSource.close();
                        stage.textContent = '✅ Completed!';
                        progressBar.style.backgroundColor = '#28a745';
                        log.innerHTML += "\\n\\nOperation finished. Redirecting...";
                        
                        let redirectTarget = "{{ url_for('list_files') }}";
                        if (finalUrl) {
                            redirectTarget = "{{ url_for('operation_complete') }}?url=" + encodeURIComponent(finalUrl);
                        } else if (data.pcloud_success) {
                             redirectTarget = "{{ url_for('operation_complete') }}?pcloud_success=true";
                        } else if (data.pcloud_action) {
                             redirectTarget = "{{ url_for('pcloud_files') }}";
                        }
                        
                        setTimeout(() => { window.location.href = redirectTarget; }, 2000);
                        return;
                    }

                    if (data.error) {
                        eventSource.close();
                        stage.textContent = '❌ Error!';
                        progressBar.style.backgroundColor = '#dc3545';
                        log.innerHTML += `\\n\\nERROR: ${data.error}`;
                        showNotification('Operation failed: ' + data.error, 'error');
                        return;
                    }

                    if (data.stage) {
                        stage.textContent = data.stage;
                    }
                    if (data.percent) {
                        progressBar.style.width = data.percent + '%';
                        progressBar.textContent = data.percent.toFixed(1) + '%';
                    }
                    if (data.log) {
                        log.innerHTML += data.log + '\\n';
                        log.scrollTop = log.scrollHeight;
                    }
                } catch (e) {
                    console.error('Error parsing SSE data:', e);
                }
            };

            eventSource.onerror = function(err) {
                stage.textContent = 'Connection error. Please refresh.';
                eventSource.close();
                console.error('SSE error:', err);
            };
        {% endif %}
    });
</script>
</body>
</html>
"""

ENCODE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Encode Video</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; background-color: #f4f4f9; color: #333; margin: 0; padding: 20px; }
        .container { max-width: 800px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1, h2, h3 { color: #444; }
        hr { border: 0; border-top: 1px solid #ddd; margin: 20px 0; }
        input[type="text"], input[type="number"], select { width: 100%; padding: 8px; margin: 5px 0 15px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
        button { background-color: #007bff; color: white; padding: 10px 15px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
        button:hover { background-color: #0056b3; }
        a { color: #007bff; text-decoration: none; }
        a:hover { text-decoration: underline; }
        .flash-msg { padding: 10px; border-radius: 4px; margin-bottom: 15px; }
        .flash-success { background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .flash-error { background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .progress-container { display: none; margin-top: 20px; }
        .progress-bar { width: 100%; background-color: #e9ecef; border-radius: 4px; }
        .progress-bar-inner { width: 0%; height: 24px; background-color: #28a745; text-align: center; line-height: 24px; color: white; border-radius: 4px; transition: width 0.4s ease; }
        #progress-log { margin-top: 10px; font-family: monospace; font-size: 12px; max-height: 200px; overflow-y: auto; background: #333; color: #fff; padding: 10px; border-radius: 4px; }
    </style>
</head>
<body>
<div class="container">
    <h1>Encode Video: {{ filepath }}</h1>
    {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
            {% for category, message in messages %}
                <div class="flash-msg flash-{{ category }}">{{ message|safe }}</div>
            {% endfor %}
        {% endif %}
    {% endwith %}

    <div id="progress-container" class="progress-container">
        <h3 id="progress-stage">Starting...</h3>
        <div class="progress-bar">
            <div id="progress-bar-inner" class="progress-bar-inner">0%</div>
        </div>
        <pre id="progress-log"></pre>
    </div>

    <form method="POST" onsubmit="return validateEncodeForm()">
        <input type="hidden" name="pcloud_path" value="{{ pcloud_path }}">
        <label>Output Filename (relative to downloads folder):</label><br>
        <input type="text" name="output_filename" value="{{ suggested_output }}" required><br>
        
        <label>Codec:</label><br>
        <select name="codec" id="codec" required>
            <option value="none" {% if codec == "none" %}selected{% endif %}>No Encoding (Copy)</option>
            <option value="h265" {% if codec == "h265" %}selected{% endif %}>Encode to H.265 (x265)</option>
            <option value="av1" {% if codec == "av1" %}selected{% endif %}>Encode to AV1 (SVT-AV1)</option>
        </select><br>
        
        <div id="encoding-options" style="display: {% if codec != 'none' %}block{% else %}none{% endif %};">
            <label>Encoding Mode:</label><br>
            <select name="pass_mode" id="pass_mode">
                <option value="1-pass" {% if pass_mode == "1-pass" %}selected{% endif %}>1-pass (CRF)</option>
                <option value="2-pass" {% if pass_mode == "2-pass" %}selected{% endif %}>2-pass (VBR)</option>
            </select><br>
            <label>Preset (slower = better quality/smaller file):</label><br>
            <select name="preset" id="preset"></select><br>

            <label>Video Bitrate (kb/s, optional):</label><br>
            <input type="number" name="bitrate" id="bitrate" value="{{ bitrate }}" min="100" placeholder="e.g., 2000 for 2 Mbps (leave empty for default)"><br>

            <label>CRF (0–63, lower = better quality):</label><br>
            <input type="number" name="crf" id="crf" value="{{ crf|default(28 if codec == 'h265' else 35) }}" min="0" max="63" step="1" placeholder="e.g., 28 for H.265, 35 for AV1"><br>

            <label>Audio Bitrate (kb/s):</label><br>
            <input type="number" name="audio_bitrate" id="audio_bitrate" value="{{ audio_bitrate|default('96') }}" min="32" max="512" step="8" placeholder="e.g., 64, 96, 128"><br>

            <label>Frame Rate (optional):</label><br>
            <select name="fps">
                <option value="">Original</option>
                <option value="24">24 fps</option>
                <option value="30">30 fps</option>
                <option value="60">60 fps</option>
            </select><br>

            <label><input type="checkbox" name="force_stereo" value="true"> Force Stereo (2-channel) Audio</label><br>
        </div>
        
        <script>
            const codecSelect = document.getElementById('codec');
            const presetSelect = document.getElementById('preset');
            const crfInput = document.getElementById('crf');
            const passModeSelect = document.getElementById('pass_mode');
            const bitrateInput = document.getElementById('bitrate');

            function updatePresetOptions() {
                const codec = codecSelect.value;
                presetSelect.innerHTML = '';
                if (codec === 'av1') {
                    for (let p = 0; p <= 13; p++) {
                        let label = p.toString();
                        if (p === 0) label += ' (slowest)';
                        else if (p === 13) label += ' (fastest)';
                        else if (p > 7) label += ' (fast)';
                        else label += ' (medium)';
                        const option = document.createElement('option');
                        option.value = p;
                        option.text = label;
                        if (p === 6) option.selected = true;
                        presetSelect.appendChild(option);
                    }
                    crfInput.value = crfInput.value || '35';
                    crfInput.placeholder = 'e.g., 35 for AV1';
                } else if (codec === 'h265') {
                    const presets = ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow', 'placebo'];
                    presets.forEach(p => {
                        const option = document.createElement('option');
                        option.value = p;
                        option.text = p;
                        if (p === 'faster') option.selected = true;
                        presetSelect.appendChild(option);
                    });
                    crfInput.value = crfInput.value || '28';
                    crfInput.placeholder = 'e.g., 28 for H.265';
                }
                const encodingOptions = document.getElementById('encoding-options');
                encodingOptions.style.display = codec !== 'none' ? 'block' : 'none';
                
                if (codec === 'none') {
                    bitrateInput.removeAttribute('required');
                    bitrateInput.removeAttribute('min');
                    bitrateInput.value = '';
                } else {
                    bitrateInput.setAttribute('min', '100');
                    if (passModeSelect.value === '2-pass') {
                        bitrateInput.setAttribute('required', 'required');
                    } else {
                        bitrateInput.removeAttribute('required');
                    }
                }
            }

            function validateEncodeForm() {
                const codec = codecSelect.value;
                if (codec !== 'none') {
                    if (!presetSelect.value) {
                        alert('Please select a preset.');
                        return false;
                    }
                    if (passModeSelect.value === '2-pass' && (!bitrateInput.value || parseInt(bitrateInput.value) < 100)) {
                        alert('Please specify a valid video bitrate (minimum 100) for 2-pass encoding.');
                        return false;
                    }
                }
                return true;
            }

            codecSelect.addEventListener('change', updatePresetOptions);
            passModeSelect.addEventListener('change', function() {
                if (codecSelect.value !== 'none') {
                    if (this.value === '2-pass') {
                        bitrateInput.setAttribute('required', 'required');
                    } else {
                        bitrateInput.removeAttribute('required');
                    }
                }
            });

            document.addEventListener('DOMContentLoaded', updatePresetOptions);
        </script>
        
        <br>
        <label><input type="checkbox" name="upload_pixeldrain" value="true"> Upload to Pixeldrain after completion</label><br>
        <label><input type="checkbox" name="upload_pcloud" value="true"> Upload to pCloud after completion</label><br><br>
        <button type="submit">Start Encoding</button>
        <a href="{{ url_for('list_files') }}">Back to Files</a>
    </form>
</div>

<script>
    document.addEventListener("DOMContentLoaded", function() {
        {% if download_started %}
            const progressContainer = document.getElementById('progress-container');
            const stage = document.getElementById('progress-stage');
            const progressBar = document.getElementById('progress-bar-inner');
            const log = document.getElementById('progress-log');
            
            progressContainer.style.display = 'block';

            const eventSource = new EventSource("{{ url_for('progress_stream') }}");
            let finalUrl = null; // Variable to store the final URL
            
            eventSource.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);
                    
                    if (data.final_url) {
                        finalUrl = data.final_url;
                    }

                    if (data.log && data.log === 'DONE') {
                        eventSource.close();
                        stage.textContent = '✅ Completed!';
                        progressBar.style.backgroundColor = '#28a745';
                        log.innerHTML += "\\n\\nOperation finished. Redirecting...";
                        
                        let redirectTarget = "{{ url_for('list_files') }}";
                        if (finalUrl) {
                            redirectTarget = "{{ url_for('operation_complete') }}?url=" + encodeURIComponent(finalUrl);
                        } else if (data.pcloud_success) {
                             redirectTarget = "{{ url_for('operation_complete') }}?pcloud_success=true";
                        }
                        
                        setTimeout(() => { window.location.href = redirectTarget; }, 2000);
                        return;
                    }

                    if (data.error) {
                        eventSource.close();
                        stage.textContent = '❌ Error!';
                        progressBar.style.backgroundColor = '#dc3545';
                        log.innerHTML += `\\n\\nERROR: ${data.error}`;
                        return;
                    }

                    if (data.stage) {
                        stage.textContent = data.stage;
                    }
                    if (data.percent) {
                        progressBar.style.width = data.percent + '%';
                        progressBar.textContent = data.percent.toFixed(1) + '%';
                    }
                    if (data.log) {
                        log.innerHTML += data.log + '\\n';
                        log.scrollTop = log.scrollHeight;
                    }
                } catch (e) {
                    console.error('Error parsing SSE data:', e);
                }
            };

            eventSource.onerror = function(err) {
                stage.textContent = 'Connection error. Please refresh.';
                eventSource.close();
                console.error('SSE error:', err);
            };
        {% endif %}
    });
</script>
</body>
</html>
"""

FILE_OPERATION_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Processing...</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; background-color: #f4f4f9; color: #333; margin: 0; padding: 20px; }
        .container { max-width: 800px; margin: auto; background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1, h2, h3 { color: #444; }
        pre { background-color: #eee; padding: 10px; border-radius: 4px; white-space: pre-wrap; word-wrap: break-word; }
        .progress-container { display: block; margin-top: 20px; }
        .progress-bar { width: 100%; background-color: #e9ecef; border-radius: 4px; }
        .progress-bar-inner { width: 0%; height: 24px; background-color: #17a2b8; text-align: center; line-height: 24px; color: white; border-radius: 4px; transition: width 0.4s ease; }
        #progress-log { margin-top: 10px; font-family: monospace; font-size: 12px; max-height: 200px; overflow-y: auto; background: #333; color: #fff; padding: 10px; border-radius: 4px; }
    </style>
</head>
<body>
<div class="container">
    <h1>{{ operation_title }}</h1>
    <p>Please wait while the operation completes. You will be redirected automatically.</p>
    <div id="progress-container" class="progress-container">
        <h3 id="progress-stage">Starting...</h3>
        <div class="progress-bar">
            <div id="progress-bar-inner" class="progress-bar-inner" style="background-color: #17a2b8;">0%</div>
        </div>
        <pre id="progress-log"></pre>
    </div>
</div>

<script>
    document.addEventListener("DOMContentLoaded", function() {
        {% if download_started %}
            const stage = document.getElementById('progress-stage');
            const progressBar = document.getElementById('progress-bar-inner');
            const log = document.getElementById('progress-log');
            
            const eventSource = new EventSource("{{ url_for('progress_stream') }}");
            let finalUrl = null; // To store the final URL from the upload
            
            eventSource.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);

                    if (data.final_url) {
                        finalUrl = data.final_url;
                    }

                    if (data.log && data.log === 'DONE') {
                        eventSource.close();
                        stage.textContent = '✅ Completed!';
                        progressBar.style.backgroundColor = '#28a745';
                        log.innerHTML += "\\n\\nOperation finished. Redirecting...";
                        
                        let redirectTarget = "{{ url_for('list_files') }}";
                        if (finalUrl) {
                            redirectTarget = "{{ url_for('operation_complete') }}?url=" + encodeURIComponent(finalUrl);
                        } else if (data.pcloud_success) {
                             redirectTarget = "{{ url_for('operation_complete') }}?pcloud_success=true";
                        } else if (data.pcloud_action_success) {
                             redirectTarget = "{{ url_for('pcloud_files') }}?feedback=" + encodeURIComponent(data.pcloud_action_success);
                        }
                        
                        setTimeout(() => { window.location.href = redirectTarget; }, 2000);
                        return;
                    }

                    if (data.error) {
                        eventSource.close();
                        stage.textContent = '❌ Error!';
                        progressBar.style.backgroundColor = '#dc3545';
                        log.innerHTML += `\\n\\nERROR: ${data.error}`;
                        return;
                    }

                    if (data.stage) {
                        stage.textContent = data.stage;
                    }
                    if (data.percent) {
                        progressBar.style.width = data.percent + '%';
                        progressBar.textContent = data.percent.toFixed(1) + '%';
                    }
                    if (data.log) {
                        log.innerHTML += data.log + '\\n';
                        log.scrollTop = log.scrollHeight;
                    }
                } catch (e) {
                    console.error('Error parsing SSE data:', e);
                }
            };

            eventSource.onerror = function(err) {
                stage.textContent = 'Connection error. Please refresh.';
                eventSource.close();
                console.error('SSE error:', err);
            };
        {% endif %}
    });
</script>
</body>
</html>
"""

# -----------------------------
# Helper Functions
# -----------------------------
def get_pcloud_client():
    """
    Authenticates with pCloud using a stored token, or password if no token exists.
    Saves the new token upon successful password authentication.
    """
    access_token = None
    if os.path.exists(PCLOUD_TOKEN_FILE):
        try:
            with open(PCLOUD_TOKEN_FILE, 'r') as f:
                token_data = json.load(f)
                access_token = token_data.get('access_token')
                print("💡 Found pCloud access token file.")
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ Could not read pCloud token file: {e}")
            access_token = None

    if access_token:
        try:
            pc = PyCloud(access_token=access_token)
            pc.userinfo()
            print("✅ Successfully authenticated with pCloud token.")
            return pc
        except Exception as e:
            print(f"⚠️ pCloud token is invalid or expired: {e}. Re-authenticating with password.")
            if os.path.exists(PCLOUD_TOKEN_FILE): os.remove(PCLOUD_TOKEN_FILE)

    print("🔑 Authenticating with pCloud email and password...")
    try:
        pc = PyCloud(PCLOUD_EMAIL, PCLOUD_PASSWORD)
        new_token = getattr(pc, 'token', None) or getattr(pc, 'auth', {}).get('auth')
        if new_token:
            with open(PCLOUD_TOKEN_FILE, 'w') as f:
                json.dump({'access_token': new_token}, f)
            print(f"💾 Saved new pCloud token to {PCLOUD_TOKEN_FILE}")
        else:
            print("⚠️ Warning: Could not extract token from pCloud client — continuing without saving.")
        return pc
    except Exception as e:
        print(f"❌ CRITICAL: pCloud password authentication failed: {e}")
        raise e

def human_size(size_bytes):
    if size_bytes is None or size_bytes == 0:
        return "0 B"
    power = 1024
    n = 0
    power_labels = {0: '', 1: 'K', 2: 'M', 3: 'G', 4: 'T'}
    while size_bytes >= power and n < len(power_labels) -1 :
        size_bytes /= power
        n += 1
    return f"{size_bytes:.1f} {power_labels[n]}iB"

def get_safe_filename(name):
    """Sanitizes a string to be a valid filename component, allowing slashes for paths."""
    parts = name.split('/')
    safe_parts = [re.sub(r'[\\*?:"<>|]', "_", part) for part in parts]
    safe_parts = [re.sub(r'\s+', ' ', part).strip() for part in safe_parts]
    return '/'.join(safe_parts)

def get_file_size(file_path):
    try:
        return human_size(os.path.getsize(file_path))
    except FileNotFoundError:
        return "N/A"

def is_media_file(file_path):
    video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.mpg', '.mpeg', '.ts', '.vob'}
    audio_extensions = {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a', '.opus'}
    ext = os.path.splitext(os.path.basename(file_path))[1].lower()
    return ext in video_extensions or ext in audio_extensions

def get_media_info(file_path):
    """Fetches media information using ffprobe."""
    try:
        command = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", file_path
        ]
        result = subprocess.check_output(command, stderr=subprocess.STDOUT)
        data = json.loads(result)
        
        info = {}
        
        video_stream = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
        audio_stream = next((s for s in data.get('streams', []) if s.get('codec_type') == 'audio'), None)

        if video_stream:
            info['video_codec'] = video_stream.get('codec_name', 'N/A')
            fr_str = video_stream.get('avg_frame_rate', '0/1')
            if '/' in fr_str and fr_str != '0/1':
                num, den = map(int, fr_str.split('/'))
                info['video_fps'] = f"{num / den:.2f}" if den else '0.00'
            else:
                 info['video_fps'] = 'N/A'
            
            v_br = video_stream.get('bit_rate')
            if not v_br and 'format' in data: v_br = data['format'].get('bit_rate')
            info['video_bitrate'] = f"{int(v_br) // 1000} kbps" if v_br else 'N/A'
        
        if audio_stream:
            info['audio_codec'] = audio_stream.get('codec_name', 'N/A')
            a_br = audio_stream.get('bit_rate')
            info['audio_bitrate'] = f"{int(a_br) // 1000} kbps" if a_br else 'N/A'
            
        return info
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        print(f"Error fetching media info for {file_path}: {e}")
        return {"error": "Could not retrieve media information."}

def fetch_formats(url):
    try:
        ydl_opts = {'quiet': True}
        if os.path.exists(COOKIES_FILE):
            ydl_opts['cookiefile'] = COOKIES_FILE
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        formats = info.get('formats', [])
        video_formats, audio_formats, raw_lines = [], [], []

        for f in formats:
            if not f.get('format_id'): continue
            fid, ext = f['format_id'], f.get('ext', 'u')
            height, width = f.get('height'), f.get('width')
            vcodec, acodec = f.get('vcodec'), f.get('acodec')
            fps = f.get('fps')
            size_bytes = f.get('filesize') or f.get('filesize_approx')
            res = f"{width}x{height}" if height else "audio"
            fps_int = int(fps) if fps else 0
            size = human_size(size_bytes)
            raw_lines.append(f"{fid:>3} {ext:<7} {res:<9} {fps_int:>3}fps {size:<10} {vcodec or 'none':<12} {acodec or 'none'}")
            is_video = vcodec and vcodec != 'none' and height
            is_audio = acodec and acodec != 'none'

            if is_audio and not is_video:
                abr = f.get('abr', 0)
                audio_formats.append({'id': fid, 'display': f"{acodec.upper()} | {int(abr)}k | ({size})", 'br': abr or 0})
            elif is_video:
                br = f.get('tbr') or f.get('vbr') or 0
                video_formats.append({
                    'id': fid, 'display': f"{height}p | {fps_int}fps | {vcodec.upper()} | {int(br)}k | ({size})",
                    'h': height, 'fps': fps_int, 'is_muxed': is_audio
                })
        
        video_formats.sort(key=lambda x: (x.get('h', 0), x.get('fps', 0)), reverse=True)
        audio_formats.sort(key=lambda x: x.get('br', 0), reverse=True)
        return '\n'.join(raw_lines), video_formats, audio_formats
    except Exception as e:
        flash(f"❌ Error fetching formats: {str(e)}", "error")
        return "", [], []

def get_original_filename(url):
    try:
        ydl_opts = {'quiet': True}
        if os.path.exists(COOKIES_FILE): ydl_opts['cookiefile'] = COOKIES_FILE
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        title = info.get('title', 'download').strip()
        return f"{re.sub(r'[\\/*?:\"<>|]', '_', title)}.mkv"
    except Exception:
        return "download.mkv"

def run_command_with_progress(command, stage, q):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, encoding='utf-8', errors='ignore')
    for line in iter(process.stdout.readline, ''):
        q.put({"log": line.strip()})
        match = re.search(r'\[download\]\s+([0-9.]+)%', line)
        if match:
            q.put({"stage": stage, "percent": float(match.group(1))})
    if process.wait() != 0:
        raise subprocess.CalledProcessError(process.returncode, command)

def upload_to_pixeldrain(file_path, filename, q):
    try:
        q.put({"stage": f"Uploading '{filename}' to Pixeldrain...", "percent": 10})
        api_url = "https://pixeldrain.com/api/file"
        with open(file_path, 'rb') as f:
            files = {'file': (filename, f)}
            auth = ('', PIXELDRAIN_API_KEY) if PIXELDRAIN_API_KEY else None
            q.put({"stage": "Sending data...", "percent": 50})
            response = requests.post(api_url, files=files, auth=auth)
        response.raise_for_status()
        result = response.json()
        if result.get("success"):
            file_id = result.get("id")
            pixeldrain_url = f"https://pixeldrain.com/u/{file_id}"
            q.put({"stage": "✅ Pixeldrain Upload Complete!", "percent": 100})
            q.put({"log": f"Success! Link: {pixeldrain_url}", "final_url": pixeldrain_url})
        else:
            q.put({"error": f"Pixeldrain API error: {result.get('message', 'Unknown')}"})
    except Exception as e:
        q.put({"error": f"Pixeldrain upload failed: {str(e)}"})
    finally:
        q.put({"log": "DONE"})

def upload_to_pcloud(file_path, filename, q):
    try:
        q.put({"stage": f"Uploading '{filename}' to pCloud...", "percent": 10})
        pc = get_pcloud_client()
        pc.createfolderifnotexists(path=f"/{PCLOUD_FOLDER}")
        q.put({"stage": "Sending data to pCloud...", "percent": 50})
        result = pc.uploadfile(files=[file_path], path=f"/{PCLOUD_FOLDER}")
        if result and result.get('metadata'):
            q.put({"stage": "✅ pCloud Upload Complete!", "percent": 100})
            q.put({"log": f"Uploaded '{filename}' to pCloud.", "pcloud_success": True})
        else:
            q.put({"error": f"pCloud API error: {result.get('error', 'Unknown')}"})
    except Exception as e:
        q.put({"error": f"pCloud upload failed: {str(e)}"})
    finally:
        q.put({"log": "DONE"})

def get_media_duration(file_path):
    if not is_media_file(file_path): return 0
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", file_path]
        duration_str = subprocess.check_output(cmd, universal_newlines=True, stderr=subprocess.DEVNULL).strip()
        return float(duration_str) if duration_str else 0
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return 0

def get_audio_channels(file_path):
    try:
        cmd = ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels", "-of", "default=noprint_wrappers=1:nokey=1", file_path]
        channels_str = subprocess.check_output(cmd, universal_newlines=True, stderr=subprocess.DEVNULL).strip()
        return int(channels_str) if channels_str else 2
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        return 2

def encode_file(input_path, output_filename, codec, preset, pass_mode, bitrate, crf, audio_bitrate, fps, force_stereo, q, **kwargs):
    safe_output = get_safe_filename(output_filename)
    output_path = os.path.join(DOWNLOAD_FOLDER, safe_output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if os.path.exists(output_path): os.remove(output_path)
    
    try:
        while not q.empty(): q.get()
        q.put({"stage": "Initializing encoding...", "percent": 0})
        if not is_media_file(input_path):
            q.put({"error": "File type cannot be encoded."}); return
        
        duration = get_media_duration(input_path)
        if codec == "none":
            shutil.copy2(input_path, output_path)
            q.put({"stage": "✅ Copied!", "percent": 100})
        else:
            stage_msg = f"Encoding to {codec.upper()}..."
            q.put({"stage": stage_msg, "percent": 0})
            ffmpeg_cmd = ["ffmpeg", "-y", "-i", input_path]
            video_codec = "libx265" if codec == "h265" else "libsvtav1"
            
            if pass_mode == "2-pass":
                bitrate_val = int(bitrate) if bitrate and bitrate.strip() else 0
                if bitrate_val < 100: q.put({"error": "Bitrate required for 2-pass."}); return
                video_opts = ["-c:v", video_codec, "-preset", preset, "-b:v", f"{bitrate_val}k"]
                pass1_cmd = ffmpeg_cmd + video_opts + ["-pass", "1", "-an", "-f", "null", "-"]
                subprocess.run(pass1_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                ffmpeg_cmd.extend(video_opts + ["-pass", "2"])
            else:
                crf_val = int(crf) if crf else (28 if codec == 'h265' else 35)
                ffmpeg_cmd.extend(["-c:v", video_codec, "-preset", preset, "-crf", str(crf_val)])

            if fps: ffmpeg_cmd.extend(["-r", fps])
            audio_bitrate_val = int(audio_bitrate) if audio_bitrate else 96
            ffmpeg_cmd.extend(["-ac", "2" if force_stereo else str(get_audio_channels(input_path)), "-c:a", "libopus", "-b:a", f"{audio_bitrate_val}k"])
            ffmpeg_cmd.append(output_path)

            process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, encoding='utf-8', errors='ignore')
            for line in iter(process.stdout.readline, ''):
                q.put({"log": line.strip()})
                if duration > 0:
                    match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})', line)
                    if match:
                        h, m, s, ms = map(int, match.groups())
                        percent = min(100, ((h*3600 + m*60 + s + ms/100) / duration) * 100)
                        q.put({"stage": stage_msg, "percent": percent})
            if process.wait() != 0: raise subprocess.CalledProcessError(process.returncode, ffmpeg_cmd)
            q.put({"stage": "✅ Encoding Complete!", "percent": 100})

        if kwargs.get("upload_pixeldrain"):
            upload_to_pixeldrain(output_path, os.path.basename(safe_output), q)
        if kwargs.get("upload_pcloud"):
            upload_to_pcloud(output_path, os.path.basename(safe_output), q)
    except Exception as e:
        q.put({"error": str(e)})
    finally:
        q.put({"log": "DONE"})

def download_file_directly(url, q, upload_pixeldrain_direct=False, upload_pcloud_direct=False):
    try:
        while not q.empty(): q.get()
        q.put({"stage": "Starting direct download...", "percent": 0})
        with requests.get(url, stream=True, allow_redirects=True, headers={'User-Agent': 'Mozilla/5.0'}) as r:
            r.raise_for_status()
            filename = "direct_download"
            cd_header = r.headers.get('content-disposition')
            if cd_header:
                match = re.search(r"filename\*=([^']*)''([^;]*)", cd_header) or re.search(r'filename="?([^"]+)"?', cd_header)
                if match: filename = unquote(match.group(1))
            if filename == "direct_download":
                filename_from_url = url.split('/')[-1].split('?')[0]
                if filename_from_url: filename = unquote(filename_from_url)
            
            safe_name = get_safe_filename(filename)
            final_path = os.path.join(DOWNLOAD_FOLDER, safe_name)
            total_size = int(r.headers.get('content-length', 0))
            downloaded_size = 0
            os.makedirs(os.path.dirname(final_path), exist_ok=True)
            with open(final_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk); downloaded_size += len(chunk)
                    if total_size > 0:
                        q.put({"stage": "Downloading...", "percent": (downloaded_size / total_size) * 100})
        q.put({"stage": "✅ Download complete!", "percent": 100})
        if upload_pixeldrain_direct: upload_to_pixeldrain(final_path, safe_name, q)
        if upload_pcloud_direct: upload_to_pcloud(final_path, safe_name, q)
    except Exception as e:
        q.put({"error": f"Direct download failed: {str(e)}"})
    finally:
        q.put({"log": "DONE"})

def upload_file_directly_to_pixeldrain(url, q):
    try:
        while not q.empty(): q.get()
        q.put({"stage": "Starting direct remote upload...", "percent": 0})
        with requests.get(url, stream=True, allow_redirects=True, headers={'User-Agent': 'Mozilla/5.0'}) as r:
            r.raise_for_status()
            filename = "direct_upload"
            cd_header = r.headers.get('content-disposition')
            if cd_header:
                match = re.search(r"filename\*=([^']*)''([^;]*)", cd_header) or re.search(r'filename="?([^"]+)"?', cd_header)
                if match: filename = unquote(match.group(1))
            if filename == "direct_upload":
                filename_from_url = url.split('/')[-1].split('?')[0]
                if filename_from_url: filename = unquote(filename_from_url)

            q.put({"log": f"Identified filename: '{filename}'"})
            api_url = "https://pixeldrain.com/api/file"
            files = {'file': (filename, r.raw, r.headers.get('content-type', 'application/octet-stream'))}
            auth = ('', PIXELDRAIN_API_KEY) if PIXELDRAIN_API_KEY else None
            response = requests.post(api_url, files=files, auth=auth, stream=True)
            response.raise_for_status()
            result = response.json()
            if result.get("success"):
                pixeldrain_url = f"https://pixeldrain.com/u/{result.get('id')}"
                q.put({"stage": "✅ Upload complete!", "percent": 100, "final_url": pixeldrain_url})
            else:
                q.put({"error": f"Pixeldrain API error: {result.get('message', 'Unknown')}"})
    except Exception as e:
        q.put({"error": f"Direct remote upload failed: {str(e)}"})
    finally:
        q.put({"log": "DONE"})


def download_and_convert(url, video_id, audio_id, filename, codec, preset, pass_mode, bitrate, crf, audio_bitrate, fps, force_stereo, q, is_muxed, **kwargs):
    safe_name = get_safe_filename(filename)
    base_name, _ = os.path.splitext(safe_name)
    final_path = os.path.join(DOWNLOAD_FOLDER, safe_name)
    tmp_path_template = os.path.join(DOWNLOAD_FOLDER, base_name + ".part")
    
    try:
        while not q.empty(): q.get()
        q.put({"stage": "Initializing download...", "percent": 0})
        yt_formats = f"{video_id}+{audio_id}" if audio_id else (video_id if is_muxed else f"{video_id}+bestaudio")
        yt_dlp_cmd = ["yt-dlp", "-f", yt_formats, "-o", tmp_path_template, "--merge-output-format", "mkv", url]
        if os.path.exists(COOKIES_FILE): yt_dlp_cmd.extend(["--cookies", COOKIES_FILE])
        run_command_with_progress(yt_dlp_cmd, "Downloading with yt-dlp...", q)
        q.put({"stage": "Download Complete", "percent": 100})

        found_files = [f for f in os.listdir(DOWNLOAD_FOLDER) if f.startswith(os.path.basename(tmp_path_template))]
        if not found_files: raise FileNotFoundError("yt-dlp did not create the expected file.")
        actual_tmp_path = os.path.join(DOWNLOAD_FOLDER, found_files[0])
        
        if codec == "none":
            if os.path.exists(final_path): os.remove(final_path)
            os.rename(actual_tmp_path, final_path)
            q.put({"stage": "✅ Done!", "log": "File saved without encoding."})
        else:
            final_path = os.path.join(DOWNLOAD_FOLDER, base_name + ".mkv")
            # Collect all encode_file arguments from the current function's scope
            encode_options = {
                'input_path': actual_tmp_path, 'output_filename': os.path.basename(final_path),
                'codec': codec, 'preset': preset, 'pass_mode': pass_mode, 'bitrate': bitrate,
                'crf': crf, 'audio_bitrate': audio_bitrate, 'fps': fps, 'force_stereo': force_stereo
            }
            encode_file(**encode_options, q=q, **kwargs)
        
        # After any potential encoding, check for uploads
        if kwargs.get("upload_pixeldrain"): upload_to_pixeldrain(final_path, os.path.basename(final_path), q)
        if kwargs.get("upload_pcloud"): upload_to_pcloud(final_path, os.path.basename(final_path), q)
    except Exception as e:
        q.put({"error": str(e)})
    finally:
        if 'actual_tmp_path' in locals() and os.path.exists(actual_tmp_path):
            try: os.remove(actual_tmp_path)
            except OSError: pass
        q.put({"log": "DONE"})

def manual_merge_worker(url, video_id, audio_id, filename, q):
    """Worker to download and merge streams using manually provided IDs."""
    safe_name = get_safe_filename(filename)
    base_name, _ = os.path.splitext(safe_name)
    final_path = os.path.join(DOWNLOAD_FOLDER, base_name + ".mkv")

    try:
        while not q.empty(): q.get()
        q.put({"stage": "Initializing manual download...", "percent": 0})
        
        video_id_clean = video_id.strip()
        audio_id_clean = audio_id.strip() if audio_id else ""

        if audio_id_clean:
            format_selector = f"{video_id_clean}+{audio_id_clean}"
        else:
            format_selector = video_id_clean

        yt_dlp_cmd = ["yt-dlp", "-f", format_selector, "-o", final_path, "--merge-output-format", "mkv", url]
        if os.path.exists(COOKIES_FILE): 
            yt_dlp_cmd.extend(["--cookies", COOKIES_FILE])

        run_command_with_progress(yt_dlp_cmd, "Downloading & Merging with yt-dlp...", q)
        
        q.put({"stage": "✅ Download Complete!", "percent": 100})
    except Exception as e:
        q.put({"error": str(e)})
    finally:
        q.put({"log": "DONE"})

# -----------------------------
# Flask Routes
# -----------------------------
@app.route("/")
def index():
    if 'last_upload_url' in session:
        flash(f"✅ Upload completed! <a href='{session.pop('last_upload_url')}' target='_blank'>View Link</a>", "success")
    if 'last_pcloud_success' in session:
        session.pop('last_pcloud_success')
        flash("✅ Upload to pCloud completed successfully!", "success")
    template_vars = {
        "url": "", "formats": None, "download_started": False,
        "manual_url": "", "manual_formats_raw": None, "manual_filename": ""
    }
    return render_template_string(TEMPLATE, **template_vars)

@app.route("/", methods=["POST"])
def index_post():
    action = request.form.get("action")
    form_data = {
        "url": request.form.get("url", "").strip(),
        "manual_url": request.form.get("manual_url", "").strip(),
        "manual_formats_raw": None,
        "manual_filename": "",
        "download_started": False
    }

    if action == "fetch":
        formats_string, video_formats, audio_formats = fetch_formats(form_data["url"])
        if formats_string:
            form_data.update({
                "formats": formats_string, "video_formats": video_formats,
                "audio_formats": audio_formats, "original_name": get_original_filename(form_data["url"])
            })
            session['video_formats_for_mux_check'] = video_formats
            flash("✅ Advanced formats fetched!", "success")
        return render_template_string(TEMPLATE, **form_data)
    
    elif action == "manual_fetch":
        url = form_data["manual_url"]
        formats_raw, _, __ = fetch_formats(url)
        if formats_raw:
            form_data["manual_formats_raw"] = formats_raw
            form_data["manual_filename"] = get_original_filename(url).replace('.mkv', '')
            flash("✅ Manual formats fetched successfully!", "success")
        return render_template_string(TEMPLATE, **form_data)
    
    if action in ["download", "direct_download", "direct_upload_pixeldrain", "direct_upload_pcloud", "manual_merge"]:
        form_data["download_started"] = True
        thread_target, thread_args, thread_kwargs = None, (), {}

        if action == "download":
            video_formats = session.pop('video_formats_for_mux_check', [])
            video_id = request.form.get("video_id")
            is_muxed = any(f['id'] == video_id and f.get('is_muxed') for f in video_formats)
            thread_target = download_and_convert
            thread_args = (
                request.form.get("url"), video_id, request.form.get("audio_id"),
                request.form.get("filename"), request.form.get("codec"), request.form.get("preset"),
                request.form.get("pass_mode"), request.form.get("bitrate"), request.form.get("crf"),
                request.form.get("audio_bitrate"), request.form.get("fps"),
                request.form.get("force_stereo") == "true", progress_queue, is_muxed
            )
            thread_kwargs = {
                "upload_pixeldrain": request.form.get("upload_pixeldrain") == "true",
                "upload_pcloud": request.form.get("upload_pcloud") == "true"
            }
        
        elif action == "manual_merge":
            thread_target = manual_merge_worker
            thread_args = (
                request.form.get("manual_url"),
                request.form.get("manual_video_id"),
                request.form.get("manual_audio_id"),
                request.form.get("manual_filename"),
                progress_queue
            )
        
        elif action == "direct_download":
            thread_target = download_file_directly
            thread_args = (
                request.form.get("direct_url"), progress_queue,
                request.form.get("upload_pixeldrain_direct") == "true",
                request.form.get("upload_pcloud_direct") == "true"
            )
        
        elif action == "direct_upload_pixeldrain":
            thread_target = upload_file_directly_to_pixeldrain
            thread_args = (request.form.get("direct_url"), progress_queue)

        elif action == "direct_upload_pcloud":
            thread_target = download_file_directly
            thread_args = (request.form.get("direct_url"), progress_queue, False, True)

        if thread_target:
            task_thread = threading.Thread(target=thread_target, args=thread_args, kwargs=thread_kwargs)
            task_thread.daemon = True
            task_thread.start()
            
    return render_template_string(TEMPLATE, **form_data)

@app.route("/progress")
def progress_stream():
    def generate():
        while True:
            try:
                msg = progress_queue.get(timeout=30)
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get("log") == "DONE": break
            except queue.Empty: pass
            except GeneratorExit: break
    return Response(generate(), mimetype="text/event-stream")

@app.route("/upload_direct", methods=["POST"])
def upload_direct():
    if 'file' in request.files and request.files['file'].filename:
        file = request.files['file']
        filename = secure_filename(file.filename)
        file.save(os.path.join(DOWNLOAD_FOLDER, filename))
        thread = threading.Thread(target=upload_to_pixeldrain, args=(os.path.join(DOWNLOAD_FOLDER, filename), filename, progress_queue))
        thread.daemon = True
        thread.start()
        return render_template_string(FILE_OPERATION_TEMPLATE, operation_title=f"Uploading: {filename}", download_started=True)
    flash("No file selected", "error")
    return redirect(url_for('index'))

@app.route("/upload_local", methods=["POST"])
def upload_local():
    if 'file' in request.files and request.files['file'].filename:
        file = request.files['file']
        filename = secure_filename(file.filename)
        file_path = os.path.join(DOWNLOAD_FOLDER, filename)
        if os.path.exists(file_path):
            flash(f"File '{filename}' already exists.", "error")
        else:
            file.save(file_path)
            session['last_local_upload'] = filename
    else:
        flash("No file selected.", "error")
    return redirect(url_for('list_files'))

@app.route("/files")
def list_files():
    feedback_messages = {
        'last_upload_url': "✅ Upload to Pixeldrain completed! <a href='{}' target='_blank'>View Link</a>",
        'last_pcloud_success': "✅ Upload to pCloud completed successfully!",
        'last_deleted_file': "✅ Item deleted: {}",
        'last_renamed_file': "✅ Item renamed: {old} → {new}",
        'last_local_upload': "✅ Uploaded '{}' to server."
    }
    for key, msg_format in feedback_messages.items():
        if key in session:
            value = session.pop(key)
            flash(msg_format.format(**value) if isinstance(value, dict) else msg_format.format(value), "success")

    subpath = request.args.get("path", "").strip("/")
    current_path = os.path.join(DOWNLOAD_FOLDER, subpath)
    if not os.path.exists(current_path) or not os.path.isdir(current_path):
        flash(f"Folder not found: {subpath}", "error")
        return redirect(url_for("list_files"))

    all_items = []
    try:
        for entry in os.listdir(current_path):
            full_path = os.path.join(current_path, entry)
            rel_path = os.path.join(subpath, entry) if subpath else entry
            mtime = os.path.getmtime(full_path)
            is_dir = os.path.isdir(full_path)
            all_items.append({
                "name": entry + ("/" if is_dir else ""), "is_dir": is_dir, "size": get_file_size(full_path) if not is_dir else "-",
                "mtime": mtime, "rel_path": rel_path.replace("\\", "/"),
                "is_media": is_media_file(full_path) if not is_dir else False
            })
    except Exception as e:
        flash(f"Error listing folder: {e}", "error")

    all_items.sort(key=lambda x: (not x["is_dir"], -x["mtime"]))
    parent_path = "/".join(subpath.split("/")[:-1]) if subpath else ""
    parent_url = url_for("list_files", path=parent_path) if subpath else None
    pcloud_folder_url = f"https://my.pcloud.com/browser/folder?path={quote(f'/{PCLOUD_FOLDER}')}"

    return render_template_string("""
<!DOCTYPE html><html><head><title>Downloaded Files</title><style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background-color:#f4f4f9;color:#333;margin:20px}
.container{max-width:1000px;margin:auto;background:#fff;padding:20px;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.1)}
table{width:100%;border-collapse:collapse;margin-top:20px} th,td{padding:12px;border-bottom:1px solid #ddd;text-align:left;word-break:break-all}
th{background-color:#f2f2f2} a{color:#007bff;text-decoration:none} a:hover{text-decoration:underline}
.flash-msg{padding:10px;border-radius:4px;margin-bottom:15px} .flash-success{background-color:#d4edda;color:#155724} .flash-error{background-color:#f8d7da;color:#721c24}
button,.button-link{background-color:#007bff;color:#fff!important;padding:5px 10px;border:none;border-radius:4px;cursor:pointer;font-size:14px;margin-right:5px;text-decoration:none;display:inline-block}
button:hover,.button-link:hover{background-color:#0056b3} button.delete{background-color:#dc3545} button.delete:hover{background-color:#c82333}
button.pcloud{background-color:#8E44AD} button.pcloud:hover{background-color:#732d91} button.upload{background-color:#17a2b8} button.upload:hover{background-color:#138496}
button.encode{background-color:#28a745} button.encode:hover{background-color:#218838} button.rename{background-color:#ffc107;color:#212529!important} button.rename:hover{background-color:#e0a800}
button.info{background-color:#0dcaf0; color: #000!important} button.info:hover{background-color:#0cb9d7}
.actions{white-space:nowrap} .actions form{display:inline-block} .modal{display:none;position:fixed;z-index:1000;left:0;top:0;width:100%;height:100%;background-color:rgba(0,0,0,.5)}
.modal-content{background-color:#fff;margin:15% auto;padding:20px;border-radius:8px;width:500px;max-width:90%} .modal-content input{width:100%;padding:8px;margin:10px 0;box-sizing:border-box} .modal-content pre{background-color:#eee;font-family:monospace;padding:10px;border-radius:4px}
</style></head><body><div class="container">
<h1>Downloaded Files (Local)</h1><p><a href="{{url_for('index')}}">← Back</a> | <a href="{{url_for('pcloud_files')}}">☁️ pCloud Files</a> | <a href="{{pcloud_folder_url}}" target="_blank">↗️ Open pCloud Folder</a></p>
{% if parent_url %}<p>📁 <a href="{{parent_url}}">← Back to parent</a></p>{% endif %}<p>Path: /{{current_path}}</p>
{% with messages=get_flashed_messages(with_categories=true) %}{% for c,m in messages %}<div class="flash-msg flash-{{c}}">{{m|safe}}</div>{% endfor %}{% endwith %}
<div style="border:1px solid #ddd;padding:20px;border-radius:8px;margin:20px 0"><h3>Upload New File Here</h3>
<form method="POST" action="{{url_for('upload_local')}}" enctype="multipart/form-data"><input type="file" name="file" required><button type="submit" style="margin-top:10px">Upload</button></form></div>
{% if all_items %}<table><thead><tr><th>Name</th><th>Size</th><th>Actions</th></tr></thead><tbody>
{% for item in all_items %}<tr><td>{% if item.is_dir %}📁 <a href="{{url_for('list_files',path=item.rel_path)}}">{{item.name}}</a>{% else %}📄 {{item.name}}{% endif %}</td><td>{{item.size}}</td>
<td class="actions">{% if not item.is_dir %}<a href="{{url_for('download_file',filepath=item.rel_path)}}" class="button-link">Download</a>{% endif %}
<button onclick="showRenameModal('{{item.rel_path}}')" class="rename">Rename</button><button onclick="confirmDelete('{{item.rel_path}}')" class="delete">Delete</button>
<form method="POST" action="{{url_for('upload_to_pcloud_file')}}" style="display:inline;"><input type="hidden" name="filepath" value="{{item.rel_path}}"><button type="submit" class="pcloud">To pCloud</button></form>
<form method="POST" action="{{url_for('upload_to_pixeldrain_file')}}" style="display:inline;"><input type="hidden" name="filepath" value="{{item.rel_path}}"><button type="submit" class="upload">To Pixeldrain</button></form>
{% if item.is_media %}<a href="{{url_for('encode_page',filepath=item.rel_path)}}" class="button-link encode">Encode</a><button type="button" onclick="showInfoModal('{{item.rel_path}}')" class="info">Info</button>{% endif %}
</td></tr>{% endfor %}</tbody></table>
{% else %}<p><i>No files found here.</i></p>{% endif %}</div>
<div id="renameModal" class="modal"><div class="modal-content"><h3>Rename Item</h3><p>Current: <strong id="currentName"></strong></p>
<form method="POST" action="{{url_for('rename_file')}}"><input type="hidden" name="old_name" id="oldNameInput"><label>New Name:</label><input type="text" name="new_name" id="newNameInput" required>
<button type="submit">Rename</button><button type="button" onclick="closeRenameModal()">Cancel</button></form></div></div>
<div id="infoModal" class="modal"><div class="modal-content"><h3>Media Information</h3><p><strong>File:</strong> <span id="infoFilename"></span></p>
<pre id="infoContent"></pre><button type="button" onclick="closeInfoModal()">Close</button></div></div>
<script>
function confirmDelete(a){if(confirm(`Delete "${a}"? This is permanent.`)){const b=document.createElement('form');b.method='POST';b.action='/delete/'+a;document.body.appendChild(b);b.submit()}}
function showRenameModal(a){const b=a.endsWith('/')?a.slice(0,-1):a;document.getElementById('currentName').textContent=a;document.getElementById('oldNameInput').value=a;document.getElementById('newNameInput').value=b;document.getElementById('renameModal').style.display='block';document.getElementById('newNameInput').focus()}
function closeRenameModal(){document.getElementById('renameModal').style.display='none'}
function showInfoModal(filepath) {
  const modal = document.getElementById('infoModal');
  const content = document.getElementById('infoContent');
  const filename = document.getElementById('infoFilename');
  filename.textContent = filepath.split('/').pop();
  content.textContent = 'Fetching info...';
  modal.style.display = 'block';
  fetch(`/info/${filepath}`)
    .then(response => { if (!response.ok) { throw new Error('Network response was not ok'); } return response.json(); })
    .then(data => {
      if (data.error) {
          content.textContent = `Error: ${data.error}`;
          return;
      }
      let infoText = '';
      infoText += `Video Codec:    ${data.video_codec || 'N/A'}\\n`;
      infoText += `Frame Rate:     ${data.video_fps || 'N/A'} fps\\n`;
      infoText += `Video Bitrate:  ${data.video_bitrate || 'N/A'}\\n\\n`;
      infoText += `Audio Codec:    ${data.audio_codec || 'N/A'}\\n`;
      infoText += `Audio Bitrate:  ${data.audio_bitrate || 'N/A'}`;
      content.textContent = infoText;
    })
    .catch(error => {
      content.textContent = 'Failed to fetch media information.';
      console.error('Error:', error);
    });
}
function closeInfoModal(){document.getElementById('infoModal').style.display='none'}
window.onclick=e=>{if(e.target==document.getElementById('renameModal'))closeRenameModal();if(e.target==document.getElementById('infoModal'))closeInfoModal()};
</script></body></html>
""", all_items=all_items, current_path=subpath, parent_url=parent_url, pcloud_folder_url=pcloud_folder_url)

@app.route("/info/<path:filepath>")
def get_info(filepath):
    """API endpoint to get media info for a file."""
    full_path = os.path.join(DOWNLOAD_FOLDER, filepath)
    if not os.path.abspath(full_path).startswith(os.path.abspath(DOWNLOAD_FOLDER)):
        return jsonify({"error": "Invalid file path"}), 400
    if not os.path.exists(full_path):
        return jsonify({"error": "File not found"}), 404

    info = get_media_info(full_path)
    if "error" in info:
        return jsonify(info), 500
    
    return jsonify(info)

@app.route("/operation_complete")
def operation_complete():
    if request.args.get('url'): session['last_upload_url'] = request.args.get('url')
    if request.args.get('pcloud_success'): session['last_pcloud_success'] = True
    if request.args.get('pcloud_action_success'):
        session['last_pcloud_action_success'] = request.args.get('pcloud_action_success')
        return redirect(url_for('pcloud_files'))
    return redirect(url_for('list_files'))

@app.route("/download/<path:filepath>")
def download_file(filepath):
    return send_from_directory(DOWNLOAD_FOLDER, filepath, as_attachment=True)

@app.route("/delete/<path:filepath>", methods=["POST"])
def delete_file(filepath):
    full_path = os.path.join(DOWNLOAD_FOLDER, filepath)
    if not os.path.abspath(full_path).startswith(os.path.abspath(DOWNLOAD_FOLDER)):
        flash("Invalid path.", "error")
    elif os.path.exists(full_path):
        try:
            if os.path.isdir(full_path): shutil.rmtree(full_path)
            else: os.remove(full_path)
            session['last_deleted_file'] = filepath
        except Exception as e:
            flash(f"Error deleting: {e}", "error")
    else:
        flash("Item not found.", "error")
    return redirect(url_for('list_files'))

@app.route("/rename", methods=["POST"])
def rename_file():
    old_rel = request.form.get("old_name")
    new_rel = request.form.get("new_name")
    if not all([old_rel, new_rel]):
        flash("Missing names.", "error"); return redirect(url_for('list_files'))
    
    new_rel = get_safe_filename(new_rel.strip('/'))
    old_path = os.path.join(DOWNLOAD_FOLDER, old_rel)
    new_path = os.path.join(DOWNLOAD_FOLDER, new_rel)
    
    if not os.path.abspath(old_path).startswith(os.path.abspath(DOWNLOAD_FOLDER)) or \
       not os.path.abspath(new_path).startswith(os.path.abspath(DOWNLOAD_FOLDER)):
        flash("Invalid path.", "error")
    elif not os.path.exists(old_path):
        flash(f"Item not found: {old_rel}", "error")
    elif os.path.exists(new_path):
        flash(f"Target '{new_rel}' already exists.", "error")
    else:
        try:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            os.rename(old_path, new_path)
            session['last_renamed_file'] = {'old': old_rel, 'new': new_rel}
        except Exception as e:
            flash(f"Error renaming: {e}", "error")
    return redirect(url_for('list_files'))

@app.route("/upload_to_pixeldrain", methods=["POST"])
def upload_to_pixeldrain_file():
    filepath = request.form.get("filepath")
    full_path = os.path.join(DOWNLOAD_FOLDER, filepath)
    if not filepath or not os.path.exists(full_path):
        flash("File not found.", "error"); return redirect(url_for('list_files'))
    thread = threading.Thread(target=upload_to_pixeldrain, args=(full_path, os.path.basename(filepath), progress_queue))
    thread.daemon = True
    thread.start()
    return render_template_string(FILE_OPERATION_TEMPLATE, operation_title=f"Uploading to Pixeldrain: {os.path.basename(filepath)}", download_started=True)

@app.route("/upload_to_pcloud", methods=["POST"])
def upload_to_pcloud_file():
    filepath = request.form.get("filepath")
    full_path = os.path.join(DOWNLOAD_FOLDER, filepath)
    if not filepath or not os.path.exists(full_path):
        flash("File not found.", "error"); return redirect(url_for('list_files'))
    thread = threading.Thread(target=upload_to_pcloud, args=(full_path, os.path.basename(filepath), progress_queue))
    thread.daemon = True
    thread.start()
    return render_template_string(FILE_OPERATION_TEMPLATE, operation_title=f"Uploading to pCloud: {os.path.basename(filepath)}", download_started=True)

@app.route("/encode/<path:filepath>")
def encode_page(filepath):
    if not os.path.exists(os.path.join(DOWNLOAD_FOLDER, filepath)) or not is_media_file(filepath):
        flash("File not found or not a media file.", "error"); return redirect(url_for('list_files'))
    suggested_output = f"{os.path.splitext(filepath)[0]}_encoded.mkv"
    return render_template_string(ENCODE_TEMPLATE, filepath=filepath, suggested_output=suggested_output, download_started=False)

@app.route("/encode/<path:filepath>", methods=["POST"])
def encode_file_post(filepath):
    if not os.path.exists(os.path.join(DOWNLOAD_FOLDER, filepath)):
        flash("File not found.", "error"); return redirect(url_for('list_files'))
    
    options = {k: v for k, v in request.form.items()}
    options["upload_pixeldrain"] = "upload_pixeldrain" in request.form
    options["upload_pcloud"] = "upload_pcloud" in request.form
    thread = threading.Thread(target=encode_file, args=(os.path.join(DOWNLOAD_FOLDER, filepath),), kwargs={**options, 'q': progress_queue})
    thread.daemon = True
    thread.start()
    return render_template_string(ENCODE_TEMPLATE, filepath=filepath, suggested_output=request.form.get("output_filename"), download_started=True)

# --- pCloud Routes and Functions ---
def download_from_pcloud(pcloud_path, filename, q):
    """FIXED: Downloads a file from pCloud to the local server with progress."""
    try:
        while not q.empty(): q.get()
        q.put({"stage": f"Downloading '{filename}' from pCloud...", "percent": 0})
        pc = get_pcloud_client()
        
        link_data = pc.getfilelink(path=pcloud_path)
        if not link_data or 'hosts' not in link_data or not link_data['hosts']:
            raise Exception("pCloud API did not return a valid download host.")
        download_url = "https://" + link_data['hosts'][0] + link_data['path']
        q.put({"log": "Obtained direct download link from pCloud API."})
        
        local_path = os.path.join(DOWNLOAD_FOLDER, filename)
        if os.path.exists(local_path):
            q.put({"log": f"Overwriting existing local file '{filename}'."})
        
        with requests.get(download_url, stream=True) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            downloaded_size = 0
            with open(local_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    if total_size > 0:
                        percent = (downloaded_size / total_size) * 100
                        q.put({"stage": "Downloading from pCloud...", "percent": percent})

        q.put({"stage": "✅ Download Complete!", "percent": 100})
        q.put({"log": "File saved locally.", "pcloud_action_success": f"Downloaded '{filename}' successfully."})
    except Exception as e:
        q.put({"error": f"pCloud download failed: {str(e)}"})
    finally:
        q.put({"log": "DONE"})

def download_and_upload_to_pixeldrain(pcloud_path, filename, q):
    """FIXED: Downloads from pCloud, then uploads to Pixeldrain."""
    local_path = os.path.join(DOWNLOAD_FOLDER, filename)
    try:
        while not q.empty(): q.get()
        q.put({"stage": f"Step 1/2: Downloading '{filename}' from pCloud...", "percent": 0})
        pc = get_pcloud_client()
        
        link_data = pc.getfilelink(path=pcloud_path)
        if not link_data or 'hosts' not in link_data or not link_data['hosts']:
            raise Exception("pCloud API did not return a valid download host.")
        download_url = "https://" + link_data['hosts'][0] + link_data['path']

        with requests.get(download_url, stream=True) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            downloaded_size = 0
            with open(local_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    if total_size > 0:
                        percent = (downloaded_size / total_size) * 50
                        q.put({"stage": "Step 1/2: Downloading from pCloud...", "percent": percent})

        q.put({"stage": "Step 1/2: Download Complete!", "percent": 50})
        upload_to_pixeldrain(local_path, filename, q)
    except Exception as e:
        q.put({"error": f"pCloud to Pixeldrain process failed: {str(e)}"})
        q.put({"log": "DONE"})
    finally:
        if os.path.exists(local_path):
            try: os.remove(local_path)
            except OSError as e: q.put({"log": f"Warning: Could not clean up temp file: {e}"})

def download_and_encode(pcloud_path, filename, q, encode_options):
    """FIXED: Downloads from pCloud, then encodes the file."""
    local_path = os.path.join(DOWNLOAD_FOLDER, filename)
    try:
        while not q.empty(): q.get()
        q.put({"stage": f"Step 1/2: Downloading for encoding...", "percent": 0})
        pc = get_pcloud_client()
        
        link_data = pc.getfilelink(path=pcloud_path)
        if not link_data or 'hosts' not in link_data or not link_data['hosts']:
            raise Exception("pCloud API did not return a valid download host.")
        download_url = "https://" + link_data['hosts'][0] + link_data['path']
        
        with requests.get(download_url, stream=True) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            downloaded_size = 0
            with open(local_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    if total_size > 0:
                        percent = (downloaded_size / total_size) * 50
                        q.put({"stage": "Step 1/2: Downloading from pCloud...", "percent": percent})
        
        q.put({"stage": "Step 1/2: Download Complete!", "percent": 50})
        encode_options['input_path'] = local_path
        encode_file(**encode_options, q=q)
    except Exception as e:
        q.put({"error": f"pCloud encode process failed: {str(e)}"})
        q.put({"log": "DONE"})
    finally:
         if os.path.exists(local_path):
            try: os.remove(local_path)
            except OSError as e: q.put({"log": f"Warning: Could not clean up temp file: {e}"})

@app.route("/pcloud_files")
def pcloud_files():
    if 'last_pcloud_action_success' in session:
        flash(f"✅ {session.pop('last_pcloud_action_success')}", "success")
    if request.args.get('feedback'):
        flash(f"✅ {request.args.get('feedback')}", "success")
    try:
        pc = get_pcloud_client()
        folder_data = pc.listfolder(path=f'/{PCLOUD_FOLDER}')
        items = [
            {'name': item['name'], 'path': item['path'], 'size': human_size(item.get('size',0)), 'is_folder': item['isfolder'], 'is_media': is_media_file(item['name']), 'modified': item.get('modified','')}
            for item in folder_data.get('metadata', {}).get('contents', [])
        ]
        pcloud_folder_url = f"https://my.pcloud.com/browser/folder?path={quote(f'/{PCLOUD_FOLDER}')}"
        return render_template_string("""
<!DOCTYPE html><html><head><title>pCloud Files</title><style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background-color:#f4f4f9;color:#333;margin:20px}
.container{max-width:1000px;margin:auto;background:#fff;padding:20px;border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.1)}
h1{color:#444}table{width:100%;border-collapse:collapse;margin-top:20px}th,td{padding:12px;text-align:left;border-bottom:1px solid #ddd;word-break:break-all}
th{background-color:#f2f2f2}a{color:#007bff;text-decoration:none}a:hover{text-decoration:underline}
.button-link,button{background-color:#007bff;color:#fff!important;padding:5px 10px;border:none;border-radius:4px;cursor:pointer;margin-right:5px;font-size:14px;text-decoration:none;display:inline-block}
.button-link:hover,button:hover{background-color:#0056b3}.pcloud{background-color:#8E44AD}.pcloud:hover{background-color:#732d91}.delete{background-color:#dc3545}.delete:hover{background-color:#c82333}
.rename{background-color:#ffc107;color:#212529!important}.rename:hover{background-color:#e0a800}.upload{background-color:#17a2b8}.upload:hover{background-color:#138496}
.encode{background-color:#28a745}.encode:hover{background-color:#218838}.actions{white-space:nowrap}.flash-msg{padding:10px;border-radius:4px;margin-bottom:15px}
.flash-success{background-color:#d4edda;color:#155724}.flash-error{background-color:#f8d7da;color:#721c24}.modal{display:none;position:fixed;z-index:1000;left:0;top:0;width:100%;height:100%;background-color:rgba(0,0,0,.5)}
.modal-content{background-color:#fff;margin:15% auto;padding:20px;border-radius:8px;width:500px;max-width:90%}.modal-content input{width:100%;padding:8px;margin:10px 0;box-sizing:border-box}
</style></head><body><div class="container"><h1>pCloud Files: '/{{folder_name}}'</h1><p><a href="{{url_for('list_files')}}">← Local Files</a>
<a href="{{pcloud_folder_url}}" target="_blank" class="button-link pcloud" style="margin-left:15px">↗️ Open on pCloud.com</a></p>
{% with m=get_flashed_messages(with_categories=true)%}{%for c,msg in m%}<div class="flash-msg flash-{{c}}">{{msg|safe}}</div>{%endfor%}{%endwith%}
{%if items%}<table><thead><tr><th>Name</th><th>Size</th><th>Modified</th><th>Actions</th></tr></thead><tbody>
{% for item in items %}<tr><td>{%if item.is_folder%}<b>📁 {{item.name}}</b>{%else%}📄 {{item.name}}{%endif%}</td><td>{{item.size}}</td><td>{{item.modified}}</td>
<td class="actions">{%if not item.is_folder%}<form method="POST" action="{{url_for('pcloud_download_to_server')}}" style="display:inline"><input type="hidden" name="pcloud_path" value="{{item.path}}"><button type="submit">To Server</button></form>{%endif%}
<button onclick="srm('{{item.path}}','{{item.name}}')" class="rename">Rename</button>{%if not item.is_folder%}
<form method="POST" action="{{url_for('pcloud_upload_to_pixeldrain')}}" style="display:inline"><input type="hidden" name="pcloud_path" value="{{item.path}}"><button type="submit" class="upload">To Pixeldrain</button></form>
{%if item.is_media%}<a href="{{url_for('pcloud_encode_page',pcloud_path=item.path)}}" class="button-link encode">Encode</a>{%endif%}{%endif%}
<form method="POST" action="{{url_for('pcloud_delete')}}" style="display:inline"><input type="hidden" name="path" value="{{item.path}}"><button type="submit" class="delete" onclick="return confirm('Delete \'{{item.name}}\'?')">Delete</button></form></td></tr>
{%endfor%}</tbody></table>{%else%}<p>No files in '/{{folder_name}}'.</p>{%endif%}</div>
<div id="rm" class="modal"><div class="modal-content"><h3>Rename Item</h3><p>Current: <strong id="cn"></strong></p><label>New:</label><input type="text" id="nn"><button onclick="cr()">Rename</button><button onclick="crm()">Cancel</button></div></div>
<script>let cp='';function srm(a,b){cp=a;document.getElementById('cn').textContent=a;document.getElementById('nn').value=b;document.getElementById('rm').style.display='block';document.getElementById('nn').focus()}
function crm(){document.getElementById('rm').style.display='none'}
function cr(){const a=document.getElementById('nn').value.trim();if(a){const b=document.createElement('form');b.method='POST';b.action='{{url_for("pcloud_rename")}}';const c=document.createElement('input');c.type='hidden';c.name='old_path';c.value=cp;const d=document.createElement('input');d.type='hidden';d.name='new_name';d.value=a;b.append(c,d);document.body.appendChild(b);b.submit()}crm()}
window.onclick=e=>{if(e.target==document.getElementById('rm'))crm()};</script></body></html>
""", items=items, folder_name=PCLOUD_FOLDER, pcloud_folder_url=pcloud_folder_url)
    except Exception as e:
        flash(f"Could not connect to pCloud: {str(e)}", "error")
        return redirect(url_for('list_files'))

@app.route("/pcloud/delete", methods=["POST"])
def pcloud_delete():
    path = request.form.get("path")
    if not path: flash("Path missing.", "error"); return redirect(url_for('pcloud_files'))
    try:
        pc = get_pcloud_client()
        if path.endswith('/'): pc.deletefolderrecursive(path=path)
        else: pc.deletefile(path=path)
        session['last_pcloud_action_success'] = f"Deleted '{os.path.basename(path.strip('/'))}'."
    except Exception as e:
        flash(f"Error deleting: {str(e)}", "error")
    return redirect(url_for('pcloud_files'))

@app.route("/pcloud/rename", methods=["POST"])
def pcloud_rename():
    old_path, new_name = request.form.get("old_path"), request.form.get("new_name")
    if not old_path or not new_name: flash("Missing names.", "error"); return redirect(url_for('pcloud_files'))
    try:
        pc = get_pcloud_client()
        new_path = os.path.join(os.path.dirname(old_path), new_name)
        pc.renamefile(frompath=old_path, topath=new_path)
        session['last_pcloud_action_success'] = f"Renamed to '{new_name}'."
    except Exception as e:
        flash(f"Error renaming: {str(e)}", "error")
    return redirect(url_for('pcloud_files'))

@app.route("/pcloud/download_to_server", methods=["POST"])
def pcloud_download_to_server():
    pcloud_path = request.form.get("pcloud_path")
    filename = os.path.basename(pcloud_path)
    thread = threading.Thread(target=download_from_pcloud, args=(pcloud_path, filename, progress_queue))
    thread.daemon = True
    thread.start()
    return render_template_string(FILE_OPERATION_TEMPLATE, operation_title=f"Downloading from pCloud: {filename}", download_started=True)

@app.route("/pcloud/upload_to_pixeldrain", methods=["POST"])
def pcloud_upload_to_pixeldrain():
    pcloud_path, filename = request.form.get("pcloud_path"), os.path.basename(request.form.get("pcloud_path"))
    thread = threading.Thread(target=download_and_upload_to_pixeldrain, args=(pcloud_path, filename, progress_queue))
    thread.daemon = True
    thread.start()
    return render_template_string(FILE_OPERATION_TEMPLATE, operation_title=f"pCloud to Pixeldrain: {filename}", download_started=True)

@app.route("/pcloud/encode/<path:pcloud_path>")
def pcloud_encode_page(pcloud_path):
    filename = os.path.basename(pcloud_path)
    if not is_media_file(filename):
        flash("Not a media file.", "error"); return redirect(url_for('pcloud_files'))
    suggested_output = f"{os.path.splitext(filename)[0]}_encoded.mkv"
    return render_template_string(ENCODE_TEMPLATE, filepath=f"pCloud file: {filename}", pcloud_path=pcloud_path, suggested_output=suggested_output, download_started=False)

@app.route("/pcloud/encode/<path:pcloud_path>", methods=["POST"])
def pcloud_encode_post(pcloud_path):
    filename = os.path.basename(pcloud_path)
    encode_options = {k: v for k, v in request.form.items() if k != 'pcloud_path'}
    encode_options["upload_pixeldrain"] = "upload_pixeldrain" in request.form
    encode_options["upload_pcloud"] = "upload_pcloud" in request.form
    thread = threading.Thread(target=download_and_encode, args=(pcloud_path, filename, progress_queue, encode_options))
    thread.daemon = True
    thread.start()
    return render_template_string(ENCODE_TEMPLATE, filepath=f"pCloud file: {filename}", pcloud_path=pcloud_path, suggested_output=request.form.get("output_filename"), download_started=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=FLASK_PORT, debug=True)
