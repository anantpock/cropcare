import os
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from werkzeug.utils import secure_filename
import uuid
from flask_cors import CORS

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class Base(DeclarativeBase):
    pass

# Initialize SQLAlchemy with the Base class
db = SQLAlchemy(model_class=Base)

# Create Flask application
app = Flask(__name__)

# Configure application
app.secret_key = os.environ.get("SESSION_SECRET", "dev_secret_key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///plant_disease.db")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config["UPLOAD_FOLDER"] = "static/uploads"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max upload

# Initialize database
db.init_app(app)

# Enable CORS
CORS(app)

# Ensure upload directory exists
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Import models after db initialization to avoid circular imports
with app.app_context():
    from models import User, PlantDiseaseResult
    db.create_all()

# Import services after app creation
from plant_disease_detector import detect_disease
from gemini_service import get_treatment_recommendation, chat_with_gemini, initialize_chat

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/history')
def history():
    # Fetch the latest 20 results
    results = PlantDiseaseResult.query.order_by(PlantDiseaseResult.timestamp.desc()).limit(20).all()
    return render_template('history.html', results=results)

@app.route('/chat')
def chat():
    # Get the disease_id from the URL parameter
    disease_id = request.args.get('disease_id')
    disease_result = None
    
    if disease_id:
        disease_result = PlantDiseaseResult.query.filter_by(id=disease_id).first()
    
    return render_template('chat.html', disease_result=disease_result)

@app.route('/api/upload', methods=['POST'])
def upload_image():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    # Generate a unique filename
    filename = secure_filename(file.filename)
    file_extension = os.path.splitext(filename)[1]
    unique_filename = f"{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
    
    # Save the uploaded file
    file.save(file_path)
    
    try:
        # Process the image with the disease detection model
        prediction, confidence = detect_disease(file_path)
        
        # Save the result to the database
        result = PlantDiseaseResult(
            image_path=file_path,
            prediction=prediction,
            confidence=float(confidence),
            timestamp=datetime.now()
        )
        db.session.add(result)
        db.session.commit()
        
        return jsonify({
            'id': result.id,
            'image_path': file_path,
            'prediction': prediction,
            'confidence': confidence,
            'timestamp': result.timestamp.isoformat()
        }), 200
    
    except Exception as e:
        logger.error(f"Error processing image: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/get_treatment', methods=['POST'])
def get_treatment():
    data = request.json
    
    if not data or 'disease' not in data:
        return jsonify({'error': 'Disease name is required'}), 400
    
    disease_name = data['disease']
    
    try:
        treatment = get_treatment_recommendation(disease_name)
        return jsonify({'treatment': treatment}), 200
    
    except Exception as e:
        logger.error(f"Error getting treatment recommendation: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/results', methods=['GET'])
def get_results():
    # Get the latest results (limited to 20)
    results = PlantDiseaseResult.query.order_by(PlantDiseaseResult.timestamp.desc()).limit(20).all()
    
    results_list = [{
        'id': result.id,
        'image_path': result.image_path,
        'prediction': result.prediction,
        'confidence': result.confidence,
        'timestamp': result.timestamp.isoformat()
    } for result in results]
    
    return jsonify(results_list), 200

@app.route('/api/result/<int:result_id>', methods=['GET'])
def get_result(result_id):
    result = PlantDiseaseResult.query.get_or_404(result_id)
    
    return jsonify({
        'id': result.id,
        'image_path': result.image_path,
        'prediction': result.prediction,
        'confidence': result.confidence,
        'timestamp': result.timestamp.isoformat()
    }), 200

@app.route('/api/chat', methods=['POST'])
def handle_chat():
    data = request.json
    
    if not data or 'message' not in data:
        return jsonify({'error': 'Message is required'}), 400
    
    # Get user message and session ID
    user_message = data['message']
    
    # Get or create a session ID for this chat
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
    
    session_id = session['session_id']
    
    # Also allow overriding the session ID from the request
    if 'session_id' in data:
        session_id = data['session_id']
    
    try:
        # Get response from Gemini
        response = chat_with_gemini(session_id, user_message)
        
        return jsonify({
            'response': response,
            'session_id': session_id
        }), 200
    
    except Exception as e:
        logger.error(f"Error in chat: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Error handlers
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500

# For testing purposes only
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
