from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import threading
import time
import uuid
import shutil
from datetime import datetime, timedelta
import json

app = Flask(__name__)

# Configuration
DOWNLOAD_DIR = './downloads'
COOKIE_FILE = './cookies.txt'
CLEANUP_INTERVAL = 60  # 1 minute
FILE_EXPIRY_TIME = 300  # 5 minutes

# Create downloads directory
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Check if cookies.txt exists at startup
def initialize_cookies():
    """Check and validate cookies.txt file at startup"""
    if os.path.exists(COOKIE_FILE):
        try:
            with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    print("✓ Found and loaded cookies.txt file")
                    return True
                else:
                    print("⚠ cookies.txt is empty")
                    return False
        except Exception as e:
            print(f"⚠ Error reading cookies.txt: {e}")
            return False
    else:
        print("⚠ No cookies.txt file found - some videos may not be accessible")
        return False

# Initialize cookies on startup
cookie_status = initialize_cookies()

# Store for tracking downloads
downloads = {}

def parse_cookie_txt(cookie_content):
    """Parse cookie.txt content and create a proper cookie file"""
    try:
        # Write the cookie content to a file that yt-dlp can use
        with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
            f.write(cookie_content)
        return True
    except Exception as e:
        print(f"Error parsing cookies: {e}")
        return False

def get_yt_dlp_options(quality='best', format_type='mp4'):
    """Get yt-dlp options with latest anti-bot detection and cookie support"""
    
    # Latest Chrome headers for 2025 to avoid bot detection
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Sec-CH-UA': '"Not)A;Brand";v="99", "Google Chrome";v="127", "Chromium";v="127"',
        'Sec-CH-UA-Mobile': '?0',
        'Sec-CH-UA-Platform': '"Windows"',
        'Cache-Control': 'max-age=0',
    }
    
    options = {
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'format': f'{quality}[ext={format_type}]/best[ext={format_type}]/best',
        'noplaylist': True,
        'no_warnings': False,
        'ignoreerrors': False,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'http_headers': headers,
        'sleep_interval': 1,
        'max_sleep_interval': 5,
        'sleep_interval_subtitles': 1,
        'extractor_retries': 5,
        'file_access_retries': 5,
        'fragment_retries': 15,
        'retry_sleep_functions': {
            'http': lambda n: min(4 ** n, 60),
            'fragment': lambda n: min(4 ** n, 60),
            'file_access': lambda n: min(4 ** n, 60),
            'extractor': lambda n: min(4 ** n, 60)
        },
        # Enhanced options for latest yt-dlp
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],
                'player_skip': ['webpage'],
                'comment_sort': ['top'],
                'max_comments': ['0']
            }
        },
        # Additional anti-bot measures
        'geo_bypass': True,
        'geo_verification_proxy': None,
        # Use latest available extractors
        'prefer_free_formats': False,
        'youtube_include_dash_manifest': True,
        'extract_flat': False
    }
    
    # Add cookie file if it exists
    if os.path.exists(COOKIE_FILE):
        options['cookiefile'] = COOKIE_FILE
    
    return options

def cleanup_files():
    """Clean up old files periodically"""
    while True:
        try:
            current_time = datetime.now()
            files_to_remove = []
            
            for filename in os.listdir(DOWNLOAD_DIR):
                filepath = os.path.join(DOWNLOAD_DIR, filename)
                if os.path.isfile(filepath):
                    file_time = datetime.fromtimestamp(os.path.getctime(filepath))
                    if current_time - file_time > timedelta(seconds=FILE_EXPIRY_TIME):
                        files_to_remove.append(filepath)
            
            for filepath in files_to_remove:
                try:
                    os.remove(filepath)
                    print(f"Cleaned up: {filepath}")
                except Exception as e:
                    print(f"Error cleaning up {filepath}: {e}")
            
            # Clean up downloads tracking
            expired_downloads = []
            for download_id, info in downloads.items():
                if current_time - info['timestamp'] > timedelta(seconds=FILE_EXPIRY_TIME):
                    expired_downloads.append(download_id)
            
            for download_id in expired_downloads:
                downloads.pop(download_id, None)
                
        except Exception as e:
            print(f"Error in cleanup: {e}")
        
        time.sleep(CLEANUP_INTERVAL)

# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_files, daemon=True)
cleanup_thread.start()

@app.route('/')
def home():
    """Home page with API documentation"""
    return '''
    <h1>YouTube Video Downloader API</h1>
    <h2>Endpoints:</h2>
    <ul>
        <li><strong>POST /upload-cookies</strong> - Upload cookies.txt file</li>
        <li><strong>GET /download?url=VIDEO_URL&quality=best&format=mp4</strong> - Download video</li>
        <li><strong>GET /info?url=VIDEO_URL</strong> - Get video information</li>
        <li><strong>GET /file/DOWNLOAD_ID</strong> - Download file by ID</li>
        <li><strong>GET /status/DOWNLOAD_ID</strong> - Check download status</li>
        <li><strong>POST /set-cookies</strong> - Set cookies via JSON</li>
    </ul>
    <h2>Usage:</h2>
    <p>1. First upload your cookies.txt file using /upload-cookies</p>
    <p>2. Then use /download to get videos</p>
    <p>Quality options: worst, best, or specific like 720p, 1080p</p>
    <p>Format options: mp4, webm, mkv, etc.</p>
    '''

@app.route('/upload-cookies', methods=['POST'])
def upload_cookies():
    """Upload cookies.txt file"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Read and save cookie content
        cookie_content = file.read().decode('utf-8')
        if parse_cookie_txt(cookie_content):
            return jsonify({'message': 'Cookies uploaded successfully'})
        else:
            return jsonify({'error': 'Failed to parse cookies'}), 400
            
    except Exception as e:
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@app.route('/set-cookies', methods=['POST'])
def set_cookies():
    """Set cookies via JSON payload"""
    try:
        data = request.get_json()
        cookie_content = data.get('cookies', '')
        
        if not cookie_content:
            return jsonify({'error': 'No cookie content provided'}), 400
        
        if parse_cookie_txt(cookie_content):
            return jsonify({'message': 'Cookies set successfully'})
        else:
            return jsonify({'error': 'Failed to parse cookies'}), 400
            
    except Exception as e:
        return jsonify({'error': f'Failed to set cookies: {str(e)}'}), 500

@app.route('/info')
def get_video_info():
    """Get video information without downloading"""
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'URL parameter is required'}), 400
    
    try:
        ydl_opts = get_yt_dlp_options()
        ydl_opts['quiet'] = True
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Return relevant information
            video_info = {
                'title': info.get('title'),
                'duration': info.get('duration'),
                'uploader': info.get('uploader'),
                'upload_date': info.get('upload_date'),
                'view_count': info.get('view_count'),
                'like_count': info.get('like_count'),
                'description': info.get('description', '')[:500] + '...' if info.get('description') else '',
                'thumbnail': info.get('thumbnail'),
                'formats': [
                    {
                        'format_id': f.get('format_id'),
                        'ext': f.get('ext'),
                        'quality': f.get('format_note'),
                        'filesize': f.get('filesize')
                    } for f in info.get('formats', [])[:10]  # Limit to first 10 formats
                ]
            }
            
            return jsonify(video_info)
            
    except Exception as e:
        return jsonify({'error': f'Failed to get video info: {str(e)}'}), 500

@app.route('/download')
def download_video():
    """Download video and return download URL"""
    url = request.args.get('url')
    quality = request.args.get('quality', 'best')
    format_type = request.args.get('format', 'mp4')
    
    if not url:
        return jsonify({'error': 'URL parameter is required'}), 400
    
    download_id = str(uuid.uuid4())
    
    try:
        # Store download info
        downloads[download_id] = {
            'status': 'downloading',
            'timestamp': datetime.now(),
            'url': url,
            'filename': None,
            'error': None
        }
        
        # Get video info first
        ydl_opts = get_yt_dlp_options(quality, format_type)
        ydl_opts['quiet'] = True
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info to get title
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'video')
            
            # Sanitize filename
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            expected_filename = f"{safe_title}.{format_type}"
            expected_path = os.path.join(DOWNLOAD_DIR, expected_filename)
            
            # Download the video
            ydl.download([url])
            
            # Find the actual downloaded file
            downloaded_file = None
            for filename in os.listdir(DOWNLOAD_DIR):
                filepath = os.path.join(DOWNLOAD_DIR, filename)
                if os.path.isfile(filepath) and filename not in [f for f in downloads.values() if f.get('filename')]:
                    # Check if this is a recently created file
                    file_time = datetime.fromtimestamp(os.path.getctime(filepath))
                    if datetime.now() - file_time < timedelta(seconds=30):
                        downloaded_file = filename
                        break
            
            if downloaded_file:
                downloads[download_id]['status'] = 'completed'
                downloads[download_id]['filename'] = downloaded_file
                
                return jsonify({
                    'download_id': download_id,
                    'status': 'completed',
                    'filename': downloaded_file,
                    'download_url': f'/file/{download_id}',
                    'title': title
                })
            else:
                downloads[download_id]['status'] = 'error'
                downloads[download_id]['error'] = 'Downloaded file not found'
                return jsonify({'error': 'Downloaded file not found'}), 500
                
    except Exception as e:
        downloads[download_id]['status'] = 'error'
        downloads[download_id]['error'] = str(e)
        return jsonify({'error': f'Download failed: {str(e)}'}), 500

@app.route('/file/<download_id>')
def get_file(download_id):
    """Download file by download ID"""
    if download_id not in downloads:
        return jsonify({'error': 'Download ID not found'}), 404
    
    download_info = downloads[download_id]
    
    if download_info['status'] != 'completed':
        return jsonify({'error': f'Download not completed. Status: {download_info["status"]}'}), 400
    
    filename = download_info['filename']
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    
    return send_file(filepath, as_attachment=True, download_name=filename)

@app.route('/status/<download_id>')
def get_status(download_id):
    """Get download status"""
    if download_id not in downloads:
        return jsonify({'error': 'Download ID not found'}), 404
    
    return jsonify(downloads[download_id])

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
