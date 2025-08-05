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
DISTANCE_THRESHOLD_CM = 30


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

    last_detection_time = time.time()
    timeout_seconds = 1.0
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
                # Find the closest bottle (based on largest pixel height)
                bottles['pixel_height'] = bottles['ymax'] - bottles['ymin']
                bottles['estimated_distance'] = (K * REAL_BOTTLE_HEIGHT_CM) / bottles['pixel_height']
                closest = bottles.sort_values(by='estimated_distance').iloc[0]

                pixel_height = closest['pixel_height']
                distance_cm = closest['estimated_distance']
                x_center = (closest['xmin'] + closest['xmax']) / 2
                frame_center = frame.shape[1] / 2
                offset = x_center - frame_center
                offset_norm = offset / frame_center  # -1 to 1
                max_turn_speed = 300
                turn_speed = int(offset_norm * max_turn_speed)

                last_detection_time = time.time()
                last_distance_cm = distance_cm

                print(f"🥤 Closest bottle: Distance = {distance_cm:.2f} cm | X Offset = {offset:.2f}")

                if distance_cm - 5 > DISTANCE_THRESHOLD_CM:
                    if abs(offset_norm) > 0.1:
                        print(f"🔄 Turning with speed {turn_speed}")
                        await drive_controller.drive(np.array([0.0, 0.0, turn_speed]))
                    else:
                        print("✅ Aligned. Moving forward...")
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

    calibration_model = torch.hub.load('ultralytics/yolov5', 'custom', path=MODEL_PATH)
    calibration_model.conf = 0.3

    K = await calibrate_k(calibration_model)
    if not K:
        print("❌ Calibration failed. Exiting")
        return

    await run_camera_yolo(drive_controller, motor, client, K)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Program stopped")
