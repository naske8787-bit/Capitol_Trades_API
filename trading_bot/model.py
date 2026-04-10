import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler
from tensorflow.keras.models import Sequential, load_model
from tensorflow.keras.layers import LSTM, Dense, Dropout
import os
import joblib
from config import MODEL_PATH

SCALER_PATH = "models/scaler.pkl"

def create_model(input_shape):
    """Create LSTM model for price prediction."""
    model = Sequential()
    model.add(LSTM(50, return_sequences=True, input_shape=input_shape))
    model.add(Dropout(0.2))
    model.add(LSTM(50, return_sequences=False))
    model.add(Dropout(0.2))
    model.add(Dense(1))
    model.compile(optimizer='adam', loss='mean_squared_error')
    return model

def train_model(data, epochs=50):
    """Train the model on historical data."""
    scaler = MinMaxScaler(feature_range=(0,1))
    scaled_data = scaler.fit_transform(data['Close'].values.reshape(-1,1))

    x_train, y_train = [], []
    for i in range(60, len(scaled_data)):
        x_train.append(scaled_data[i-60:i, 0])
        y_train.append(scaled_data[i, 0])

    x_train, y_train = np.array(x_train), np.array(y_train)
    x_train = np.reshape(x_train, (x_train.shape[0], x_train.shape[1], 1))

    model = create_model((x_train.shape[1], 1))
    model.fit(x_train, y_train, epochs=epochs, batch_size=32)

    # Save model
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    model.save(MODEL_PATH)
    joblib.dump(scaler, SCALER_PATH)
    return model, scaler

def load_trained_model():
    """Load pre-trained model."""
    if os.path.exists(MODEL_PATH):
        model = load_model(MODEL_PATH)
        scaler = joblib.load(SCALER_PATH)
        return model, scaler
    else:
        raise FileNotFoundError("Model not found. Train the model first.")

def predict_price(model, scaler, recent_data):
    """Predict next price."""
    scaled_data = scaler.transform(recent_data.reshape(-1,1))
    x_input = np.array([scaled_data[-60:]])
    x_input = np.reshape(x_input, (x_input.shape[0], x_input.shape[1], 1))
    prediction = model.predict(x_input, verbose=0)
    return float(scaler.inverse_transform(prediction)[0][0])