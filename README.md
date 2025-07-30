# Example CV-Bots Project

The `cvbot` library allows you to control Fischertechnik-robots by sending commands to their actuators and querying their sensors.  
This (template) repository consists out of an example project which shows how to use it.  
While we are aiming to completely replace the original Fischertechnik-TXT-Controller, it is currently still required.

## Environment setup including the TXT-Controller

In this configuration there are two "controllers": A Raspberry Pi 5, which will run your program which uses the `cvbot` library, and the original TXT controller. Both will communicate using a WiFi network provided by the Pi.
Your hardware setup should look roughly like follows:
 - A Fischertechnik robot including the TXT-controller and battery
 - A Raspberry Pi 5
 - A voltage converter to power the Pi using the original Fischertechnik battery, connected to battery and Pi
The systems should be configured like this:
 - The Pi provides a WiFi access point called "cv-bot-<COLOR>" as soon as it finishes booting
 - The TXT-controller should log into the Pis network (Settings -> Networks -> WLAN -> cv-bot-<COLOR>). The WiFi passwords will be provided by your tutor.
 - Note down the TXT-controllers IP (Info -> WLAN) and API-Key (Settings -> API-Key)

## Environment setup for standalone usage

Coming soon&trade;

## Development enviroment setup

We recommend using VS Code and its SSH Plugin to work remotely on the Pis. This allows you to simply log into the Pis access point and develop and test directly on the Pi using SSH.
The account information will be provided by your tutor. When you are set up the following steps will help you to get started:

1. Clone this repository:
```bash
git clone https://github.com/Computer-Vision-Group-Siegen/cvbot-example.git
cd cvbot-example
```
2. Create a new virtual environment
```bash
python -m venv .venv
echo -e "\n/.venv/" >> .gitignore
source .venv/bin/activate
```
3. Install poetry and install the project into your environment
```bash
pip install poetry
poetry install --with dev
```

You can test your setup by simply executing the following commands to make the robot drive in a circle (set the environment variables to the appropriate values). 
```bash
export TXT_API_HOST="192.168.4.10"  # IP of the TXT controller
export TXT_API_PORT="80"            # Port of the TXT-API server, should nearly always be 80
export TXT_API_KEY="ABCDEFG"        # The API-Key of the TXT controller (see "Environment setup using the TXT-Controller")
python cvbot_example/__main__.py
```

## Programming using the `cvbots` library

The `cvbots` library uses Pythons `asyncio` ([https://docs.python.org/3/library/asyncio.html](https://docs.python.org/3/library/asyncio.html)) library, since controlling robots often includes commands with indeterminate runtime and asynchronous behavior. This however requires a few changes to the way you write code: 
Your program needs to be executed inside an event loop. The easiest way to achieve this is to simply wrap your programs main function like this:
```python
asyncio.run(main())
```
This command creates an event loop, handles all the async setup and teardown stuff for you and executes your main function asynchronously.
A second important change is the usage of the keyword `async`: To keep it simple, all functions that need to call async code or run asynchronously need to be marked with this keyword:
```python
async def main():
    ...
```
Inside an async function you are able to call other async functions and wait for them to finish using the keyword `await`:
```python
await asyncio.sleep(5)
```
Be aware that some functionality (e.g. sleeping) needs to be handled a little differently than in synchronous code (as simply calling `time.sleep()` will mess up the event loop).
Now, to finally use the `cvbots` library you'll first need to create a client object, symbolizing the TXT-controller:
```python
client = TxtApiClient(host, port, key)
```
This client now needs to be initialized. This is an async function, so you'll need to wait for it to finish using `await`:
```python
await client.initialize()
```
Lastly you'll need to construct a controller that can be used to control the robot using the TXT client:
```python
controller = EasyDriveController(client, DriveRobotConfiguration())
```
Now, with all of the setup out of the way, you can finally control the robots using the controller. Most, if not all, robot commands are synchronous, so you'll need to await them:
```python
await ontroller.drive(np.array([0.0, 512.0, 0.0])
```
Querying the sensors (e.g. the camera) can be done as follows:
```python
frame = await anext(controller.camera())
```
