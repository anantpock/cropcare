# Import the Flask app
from backend.app import app

# Import other necessary modules
from backend.plant_disease_detector import *
from backend.models import PlantDiseaseResult
from backend.gemini_service import get_treatment_recommendation

# Run the application in development mode
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)