import sys
import threading
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QPushButton
from PyQt5.QtCore import Qt, QTimer, QTime
import RPi.GPIO as GPIO
from time import sleep
import serial
import math
from BMI160_i2c import Driver

# Serial setup
try:
    ser = serial.Serial('/dev/serial0', 115200, timeout=1)
    print("Serial connection initialized.")
except serial.SerialException:
    print("Failed to connect via serial.")
    sys.exit(1)

# GPIO setup
DIR1, STEP1, DIR2, STEP2 = 20, 21, 8, 7
CW, CCW = 1, 0
GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(DIR1, GPIO.OUT)
GPIO.setup(STEP1, GPIO.OUT)
GPIO.setup(DIR2, GPIO.OUT)
GPIO.setup(STEP2, GPIO.OUT)

delay = 0.005

# PI controller constants and variables
Kp, Ki = 0.05, 0.005
integral1, integral2 = 0, 0
prev_error1, prev_error2 = 0, 0
smooth_ldr1, smooth_ldr2, smooth_ldr3, smooth_ldr4 = 0, 0, 0, 0
alpha = 0.1

# Global variables for GUI
current_imu_angle = 0.0
max_imu_angle = 0.0
time_of_max_imu_angle = ""
tracking_active = False

# Initialize the IMU sensor
sensor = Driver(0x69)
print('IMU sensor initialization done')

def pi_control(target, prev_error, integral):
    error = target
    integral += error
    output = Kp * error + Ki * integral
    max_step = 50
    output = max(-max_step, min(max_step, output))
    return output, error, integral

def motor_control(motor_dir_pin, motor_step_pin, direction, steps):
    if tracking_active:
        GPIO.output(motor_dir_pin, direction)
        for _ in range(abs(steps)):
            GPIO.output(motor_step_pin, GPIO.HIGH)
            sleep(delay)
            GPIO.output(motor_step_pin, GPIO.LOW)
            sleep(delay)

def ldr_thread():
    global integral1, integral2, prev_error1, prev_error2, smooth_ldr1, smooth_ldr2, smooth_ldr3, smooth_ldr4
    while True:
        if tracking_active and ser.in_waiting > 0:
            line = ser.readline().decode('utf-8').strip()
            ldr_values = line.split(',')
            if len(ldr_values) == 4:
                try:
                    smooth_ldr1 = smooth_ldr1 * (1 - alpha) + int(ldr_values[0]) * alpha
                    smooth_ldr2 = smooth_ldr2 * (1 - alpha) + int(ldr_values[1]) * alpha
                    smooth_ldr3 = smooth_ldr3 * (1 - alpha) + int(ldr_values[2]) * alpha
                    smooth_ldr4 = smooth_ldr4 * (1 - alpha) + int(ldr_values[3]) * alpha

                    difference1 = smooth_ldr1 - smooth_ldr2
                    difference2 = smooth_ldr3 - smooth_ldr4

                    direction1 = CW if difference1 < 0 else CCW
                    direction2 = CW if difference2 < 0 else CCW

                    steps1, prev_error1, integral1 = pi_control(difference1, prev_error1, integral1)
                    steps2, prev_error2, integral2 = pi_control(difference2, prev_error2, integral2)

                    threading.Thread(target=motor_control, args=(DIR1, STEP1, direction1, int(steps1))).start()
                    threading.Thread(target=motor_control, args=(DIR2, STEP2, direction2, int(steps2))).start()
                except ValueError:
                    print("Error: Non-integer values received. Check the data format.")

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.layout = QVBoxLayout()
        
        self.timeLabel = QLabel("Time: " + QTime.currentTime().toString('HH:mm:ss'))
        self.layout.addWidget(self.timeLabel)
        
        self.imuLabel = QLabel(f'Current IMU Angle: {current_imu_angle:.2f} degrees')
        self.layout.addWidget(self.imuLabel)
        
        self.maxImuLabel = QLabel(f'Highest Recorded IMU Angle: {max_imu_angle:.2f} degrees')
        self.layout.addWidget(self.maxImuLabel)
        
        self.maxTimeLabel = QLabel(f'Time of Highest IMU Angle: {time_of_max_imu_angle}')
        self.layout.addWidget(self.maxTimeLabel)

        self.startButton = QPushButton('Start Tracking', self)
        self.startButton.clicked.connect(self.start_tracking)
        self.layout.addWidget(self.startButton)

        self.stopButton = QPushButton('Stop Tracking', self)
        self.stopButton.clicked.connect(self.stop_tracking)
        self.layout.addWidget(self.stopButton)

        self.setLayout(self.layout)
        self.setWindowTitle('IMU and Motor Control Monitor')
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_clock)
        self.timer.start(1000)

    def start_tracking(self):
        global tracking_active
        tracking_active = True

    def stop_tracking(self):
        global tracking_active
        tracking_active = False

    def update_clock(self):
        self.timeLabel.setText("Time: " + QTime.currentTime().toString('HH:mm:ss'))
        self.imuLabel.setText(f'Current IMU Angle: {current_imu_angle:.2f} degrees')
        self.maxImuLabel.setText(f'Highest Recorded IMU Angle: {max_imu_angle:.2f} degrees')
        self.maxTimeLabel.setText(f'Time of Highest IMU Angle: {time_of_max_imu_angle}')

def update_imu():
    global current_imu_angle, max_imu_angle, time_of_max_imu_angle
    while True:
        if tracking_active:
            data = sensor.getMotion6()
            ax, ay, az = data[3], data[4], data[5]
            roll = math.atan2(ay, az)
            roll_deg = math.degrees(roll)
            current_imu_angle = -roll_deg
            if current_imu_angle > max_imu_angle:
                max_imu_angle = current_imu_angle
                time_of_max_imu_angle = QTime.currentTime().toString('HH:mm:ss')
        sleep(0.5)

app = QApplication(sys.argv)
window = MainWindow()
window.show()

# Start sensor and LDR threads
threading.Thread(target=update_imu, daemon=True).start()
threading.Thread(target=ldr_thread, daemon=True).start()

sys.exit(app.exec_())