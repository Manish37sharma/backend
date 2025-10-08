from flask import Flask, request, jsonify
from flask import Response
from flask_cors import CORS
from typing import List, Dict, Any
import logging
import os
import json
import pathlib
import requests

# Optional Gemini API key for summaries (Week 5)
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# --- Sample dataset (Week 2) ---
# Each resource has tags that describe it. We'll score by tag overlap with user topics.
SAMPLE_RESOURCES: List[Dict[str, Any]] = [
	{
		"title": "Flask Basics",
		"description": "Learn web development with Flask",
		"link": "https://flask.palletsprojects.com/",
		"tags": ["python", "web", "flask"]
	},
	{
		"title": "Django Overview",
		"description": "Batteries-included web framework",
		"link": "https://www.djangoproject.com/",
		"tags": ["python", "web", "django"]
	},
	{
		"title": "Pandas Intro",
		"description": "Data analysis library",
		"link": "https://pandas.pydata.org/",
		"tags": ["python", "data", "pandas"]
	},
	{
		"title": "React Docs",
		"description": "Build UIs with React",
		"link": "https://react.dev/",
		"tags": ["javascript", "react", "frontend"]
	},
	{
		"title": "Node.js Guides",
		"description": "Server-side JS runtime",
		"link": "https://nodejs.org/en/learn",
		"tags": ["javascript", "node", "backend"]
	},
]

def score_resources_by_topics(resources: List[Dict[str, Any]], topics: List[str]) -> List[Dict[str, Any]]:
	"""Return resources sorted by overlap count between resource.tags and topics."""
	normalized_topics = {t.strip().lower() for t in topics if isinstance(t, str) and t.strip()}
	logging.debug("normalized_topics=%s", list(normalized_topics))
	if not normalized_topics:
		return []
	result: List[Dict[str, Any]] = []
	for r in resources:
		tags = {str(tag).lower() for tag in r.get("tags", [])}
		score = len(tags.intersection(normalized_topics))
		logging.debug("resource=%s tags=%s score=%d", r.get("title"), list(tags), score)
		if score > 0:
			item = {k: v for k, v in r.items() if k != "tags"}
			item["score"] = score
			result.append(item)
	# highest score first; stable for same score
	result.sort(key=lambda x: (-x["score"], x["title"]))
	return result

# Week 3: Optional YouTube API integration
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')

def search_youtube_videos(query: str, max_results: int = 3) -> List[Dict[str, str]]:
	if not YOUTUBE_API_KEY or not query:
		return []
	try:
		params = {
			'part': 'snippet',
			'q': query,
			'type': 'video',
			'maxResults': str(max_results),
			'key': YOUTUBE_API_KEY
		}
		resp = requests.get('https://www.googleapis.com/youtube/v3/search', params=params, timeout=10)
		resp.raise_for_status()
		items = resp.json().get('items', [])
		videos: List[Dict[str, str]] = []
		for it in items:
			vid = (it.get('id') or {}).get('videoId')
			sn = it.get('snippet') or {}
			if not vid:
				continue
			videos.append({
				'title': sn.get('title') or 'YouTube Video',
				'description': sn.get('description') or '',
				'link': f'https://www.youtube.com/watch?v={vid}'
			})
		return videos
	except Exception:
		return []

app = Flask(__name__)
CORS(app)
logging.basicConfig(
	level=logging.DEBUG,
	format='%(asctime)s %(levelname)s %(message)s',
	filename='backend/debug.log',
	filemode='w'
)

# Week 3: simple JSON user activity storage
DATA_DIR = pathlib.Path('backend/data')
DATA_DIR.mkdir(parents=True, exist_ok=True)
ACTIVITY_FILE = DATA_DIR / 'activity.json'
if not ACTIVITY_FILE.exists():
	ACTIVITY_FILE.write_text(json.dumps({}))

def load_activity() -> Dict[str, Any]:
	try:
		return json.loads(ACTIVITY_FILE.read_text() or '{}')
	except Exception:
		return {}

def save_activity(data: Dict[str, Any]) -> None:
	ACTIVITY_FILE.write_text(json.dumps(data, indent=2))

def record_user_topics(email: str, topics: List[str]) -> None:
	data = load_activity()
	user = data.get(email) or { 'topics': [], 'completed': [], 'points': 0 }
	for t in topics:
		if isinstance(t, str) and t.strip():
			user['topics'].append(t.strip().lower())
	data[email] = user
	save_activity(data)

def get_user_topic_counts(email: str) -> Dict[str, int]:
	data = load_activity()
	user = data.get(email) or { 'topics': [], 'completed': [], 'points': 0 }
	counts: Dict[str, int] = {}
	for t in user.get('topics', []):
		counts[t] = counts.get(t, 0) + 1
	return counts

def record_completion(email: str, title: str, points_award: int = 10) -> Dict[str, Any]:
	data = load_activity()
	user = data.get(email) or { 'topics': [], 'completed': [], 'points': 0 }
	completed = set(user.get('completed') or [])
	if title not in completed:
		completed.add(title)
		user['points'] = int(user.get('points') or 0) + int(points_award)
	user['completed'] = sorted(list(completed))
	data[email] = user
	save_activity(data)
	return user

@app.get('/health')
def health():
    return jsonify({ 'status': 'ok' })

@app.post('/login')
def login():
    data = request.get_json(force=True, silent=True) or {}
    email = data.get('email')
    password = data.get('password')
    if not email or not password:
        return jsonify({ 'error': 'Missing email or password' }), 400
    # demo-only: accept any non-empty credentials and return fake token
    return jsonify({ 'token': 'demo-token', 'user': { 'email': email } })

@app.post('/recommend')
def recommend():
	# Try to parse JSON first
	data = request.get_json(silent=True) or {}
	# Fallbacks for form/raw
	if not data:
		if request.form:
			data = dict(request.form)
		elif request.data:
			try:
				import json as _json
				data = _json.loads(request.data.decode('utf-8'))
			except Exception:
				data = {}
	logging.debug("/recommend raw_data=%s parsed=%s", request.data, data)

	# inputs
	email = (data.get('email') or '').strip().lower()
	topics = data.get('topics', [])
	# also allow single 'topic'
	if not topics and isinstance(data.get('topic'), str):
		topics = [data['topic']]
	if not isinstance(topics, list):
		return jsonify({ 'error': 'topics must be a list' }), 400
	# Record user activity if email provided
	if email:
		record_user_topics(email, topics)
		user_counts = get_user_topic_counts(email)
	else:
		user_counts = {}

	# Content-based: rank by tag overlap with topics
	recs = score_resources_by_topics(SAMPLE_RESOURCES, topics)

	# Simple history boost: if a resource tag appears in user's history, +1
	if user_counts:
		boosted: List[Dict[str, Any]] = []
		for r in SAMPLE_RESOURCES:
			tags = {str(tag).lower() for tag in r.get('tags', [])}
			base = next((x for x in recs if x['title'] == r['title']), None)
			if base:
				bonus = 1 if any(tag in user_counts for tag in tags) else 0
				base = dict(base)
				base['score'] = base.get('score', 0) + bonus
				boosted.append(base)
		# re-sort after boosting
		boosted.sort(key=lambda x: (-x['score'], x['title']))
		recs = boosted

	# Optional: Add YouTube results for the first topic
	yt: List[Dict[str, Any]] = []
	if topics:
		yt = search_youtube_videos(str(topics[0]))

	return jsonify({ 'recommendations': recs, 'youtube': yt })

@app.post('/complete')
def complete():
	data = request.get_json(silent=True) or {}
	email = (data.get('email') or '').strip().lower()
	title = (data.get('title') or '').strip()
	if not email or not title:
		return jsonify({ 'error': 'email and title are required' }), 400
	user = record_completion(email, title)
	return jsonify({ 'ok': True, 'points': user.get('points', 0), 'completed': user.get('completed', []) })

@app.get('/summary')
def summary():
	email = (request.args.get('email') or '').strip().lower()
	if not email:
		return jsonify({ 'error': 'email is required' }), 400
	data = load_activity()
	user = data.get(email) or { 'topics': [], 'completed': [], 'points': 0 }
	return jsonify({
		'points': user.get('points', 0),
		'completed': user.get('completed', []),
		'topics': user.get('topics', [])
	})

@app.post('/summarize')
def summarize():
	data = request.get_json(silent=True) or {}
	text = (data.get('text') or '').strip()
	if not text:
		return jsonify({ 'error': 'text is required' }), 400
	# Week 5: If a Gemini API key exists, you could call the API here.
	# To keep local dev simple, return a naive extractive summary.
	sentences = [s.strip() for s in text.replace('\n', ' ').split('.') if s.strip()]
	summary = '. '.join(sentences[:2])
	if summary and not summary.endswith('.'):
		summary += '.'
	return jsonify({ 'summary': summary or text[:160] })

@app.get('/next-topic')
def next_topic():
	email = (request.args.get('email') or '').strip().lower()
	if not email:
		return jsonify({ 'error': 'email is required' }), 400
	counts = get_user_topic_counts(email)
	if not counts:
		return jsonify({ 'next': 'python' })
	# Suggest the least practiced among known tags to diversify learning
	# If tie, choose alphabetically
	items = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]))
	return jsonify({ 'next': items[0][0] })

@app.get('/admin/popular')
def admin_popular():
	data = load_activity()
	count_by_title: Dict[str, int] = {}
	for _, user in data.items():
		for title in user.get('completed', []) or []:
			count_by_title[title] = count_by_title.get(title, 0) + 1
	popular = sorted([ { 'title': t, 'completed': c } for t, c in count_by_title.items() ], key=lambda x: (-x['completed'], x['title']))
	return jsonify({ 'popular': popular })

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)

