import asyncio
import os
import sys
import torch
import cv2
import time
import numpy as np

from cvbot.communication.txtapiclient import TxtApiClient
from cvbot.config.drive_robot_configuration import DriveRobotConfiguration
from cvbot.controller.easy_drive_controller import EasyDriveController
from cvbot.model.servomotor import Servomotor

MODEL_PATH = 'yolov5s.pt'
REAL_BOTTLE_HEIGHT_CM = 20.01
DISTANCE_THRESHOLD_CM = 30  # Trigger hit when closer than this (in cm)


async def calibrate_k(model, camera_id=0):
    cap = cv2.VideoCapture(camera_id)
    if not cap.isOpened():
        print("❌ Failed to open camera for calibration")
        return None

    samples = []

    print("\n🔧 Starting Camera Calibration...")
    print("Place the bottle at known distances (e.g., 20cm, 30cm, etc.)")
    print("The camera will detect the bottle and ask for the real distance.")
    print("Type 'q' to finish calibration.\n")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("❌ Failed to grab frame")
                continue

            results = model(frame)
            df = results.pandas().xyxy[0]
            bottles = df[df['name'].str.lower() == 'bottle']

            if not bottles.empty:
                row = bottles.iloc[0]
                pixel_height = row['ymax'] - row['ymin']
                print(f"\n📸 Detected bottle. Pixel height = {pixel_height:.2f}")
                user_input = input("Enter real distance to bottle in cm (or 'q' to finish): ").strip()
                if user_input.lower() == 'q':
                    break
                try:
                    real_distance = float(user_input)
                    k = (pixel_height * real_distance) / REAL_BOTTLE_HEIGHT_CM
                    samples.append(k)
                    print(f"✅ Sample recorded. K = {k:.2f}")
                except ValueError:
                    print("❌ Invalid input. Try again.")
            else:
                print("⚠️ Bottle not detected. Adjust placement and try again.")

            time.sleep(1)
    finally:
        cap.release()

    if samples:
        avg_k = sum(samples) / len(samples)
        print(f"\n📏 Calibration complete. Average K = {avg_k:.2f}")
        return avg_k
    else:
        print("❌ No valid samples collected")
        return None


async def run_camera_yolo(drive_controller, motor, txtClient, K, model_path=MODEL_PATH, camera_id=0):
    model = torch.hub.load('ultralytics/yolov5', 'custom', path=model_path)
    model.conf = 0.1

    print(f"📦 Loaded model with classes: {model.names}")
    cap = cv2.VideoCapture(camera_id)
    if not cap.isOpened():
        print("❌ Failed to open camera")
        return

    print("🎥 Starting detection loop. Press Ctrl+C to exit.")
    bottle_was_hit = False

    # New state trackers for fallback logic
    last_detection_time = time.time()
    timeout_seconds = 1.0  # How long to "trust" last detection
    last_distance_cm = None

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("❌ Failed to grab frame")
                break

            results = model(frame)
            df = results.pandas().xyxy[0]
            bottles = df[df['name'].str.lower() == 'bottle']

            if not bottles.empty:
                row = bottles.iloc[0]
                pixel_height = row['ymax'] - row['ymin']
                distance_cm = (K * REAL_BOTTLE_HEIGHT_CM) / pixel_height

                # Track detection time & distance
                last_detection_time = time.time()
                last_distance_cm = distance_cm

                print(f"🥤 Bottle detected. Estimated distance: {distance_cm:.2f} cm")

                if distance_cm - 5 > DISTANCE_THRESHOLD_CM:
                    print("🚗 Too far. Moving robot forward...")
                    await drive_controller.drive(np.array([0.0, 300.0, 0.0]))
                    bottle_was_hit = False
                else:
                    print("🛑 Within range. Stopping robot.")
                    await drive_controller.stop()
                    if not bottle_was_hit:
                        bottle_was_hit = True
                        print("🤖 Hitting bottle...")
                        motor.position = 300
                        await txtClient.update_servomotors(motor)
                        await asyncio.sleep(0.5)
                        motor.position = 100
                        await txtClient.update_servomotors(motor)
                        print("🔁 Arm returned to rest")
            else:
                print("🔍 No bottle detected")

                # Use last detection to decide
                time_since_last = time.time() - last_detection_time
                if last_distance_cm is not None and last_distance_cm <= DISTANCE_THRESHOLD_CM and time_since_last < timeout_seconds:
                    print("⚠️ Recently saw bottle close. Holding position.")
                    await drive_controller.stop()
                else:
                    print("🛑 Detection lost. Stopping robot for safety.")
                    await drive_controller.stop()
                    bottle_was_hit = False

            await asyncio.sleep(0.1)
    finally:
        cap.release()
        print("📷 Camera released")


async def main():
    host = os.getenv("TXT_API_HOST", "192.168.4.18")
    port = int(os.getenv("TXT_API_PORT", 80))
    key = os.getenv("TXT_API_KEY", "fhnZo7")

    client = TxtApiClient(host, port, key)
    await client.initialize()
    drive_controller = EasyDriveController(client, DriveRobotConfiguration())

    motors = client.get_devices_by_type(Servomotor)
    if len(motors) < 1:
        print("❌ No servomotors found.")
        return

    motor = motors[0]
    motor.position = 100
    await client.update_servomotors(motor)

    # Load model for calibration
    calibration_model = torch.hub.load('ultralytics/yolov5', 'custom', path=MODEL_PATH)
    calibration_model.conf = 0.3

    # Run camera calibration first
    K = await calibrate_k(calibration_model)
    if not K:
        print("❌ Calibration failed. Exiting")
        return

    # Run bottle detection and robot movement
    await run_camera_yolo(drive_controller, motor, client, K)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Program stopped")
