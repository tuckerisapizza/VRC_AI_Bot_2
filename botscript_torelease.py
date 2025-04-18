import os
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor
import credentials
import pyttsx3
import speech_recognition as sr
from pydub import AudioSegment
from pygame import mixer, _sdl2 as devices
from pythonosc import udp_client
from hugchat import hugchat
from hugchat.login import Login
import vrchatapi
from vrchatapi.api import authentication_api, notifications_api, groups_api, worlds_api
from vrchatapi.exceptions import UnauthorizedException
from vrchatapi.models import TwoFactorAuthCode, TwoFactorEmailCode, CreateGroupInviteRequest

# Global State
engine = pyttsx3.init()
client = udp_client.SimpleUDPClient("127.0.0.1", 9000)
playback_number = 0
bot_title = "Tigerbee🐝Bot"
instance_info = "Unknown"
is_emoting = False
movement_paused = False
fail_count = 0
current_model = 1
filter_cache = set()

# Initialize HuggingChat
EMAIL = credentials.HUGGINGFACE_EMAIL
PASSWD = credentials.HUGGINGFACE_PASSWORD
sign = Login(EMAIL, PASSWD)
cookies = sign.login(cookie_dir_path="./cookies/", save_cookies=True)
chatbot = hugchat.ChatBot(default_llm=current_model, cookies=cookies.get_dict(), system_prompt=credentials.SYSTEM_PROMPT)
for model in chatbot.get_available_llm_models():
    print(model.name)

# Cache filter list once
def load_filter_list():
    global filter_cache
    with open("filtered-list.txt", "r") as file:
        filter_cache = {line.strip().lower() for line in file if line.strip()}

def is_filtered(text):
    text = text.lower()
    return any(word in text for word in filter_cache)

def move_thread():
    while True:
        if not is_emoting and not movement_paused:
            time.sleep(2.6)
            action = random.randint(1, 8)
            if action == 1:
                client.send_message("/input/Jump", [1])
                client.send_message("/input/Jump", [0])
            elif action == 6:
                client.send_message("/input/MoveForward", [1])
                time.sleep(random.uniform(1, 2))
                client.send_message("/input/MoveForward", [0])
            elif action == 4:
                client.send_message("/input/LookLeft", [1])
                time.sleep(random.uniform(0.1, 0.75))
                client.send_message("/input/LookLeft", [0])
            elif action == 2:
                client.send_message("/input/LookRight", [1])
                time.sleep(random.uniform(0.1, 0.75))
                client.send_message("/input/LookRight", [0])

def api_thread():
    
    configuration = vrchatapi.Configuration(
        username = credentials.VRCHAT_USER,
        password = credentials.VRCHAT_PASSWORD,
    )
    with vrchatapi.ApiClient(configuration) as api_client:
    #    # Set our User-Agent as per VRChat Usage Policy
        api_client.user_agent = credentials.USER_AGENT
        # Instantiate instances of API classes
        auth_api = authentication_api.AuthenticationApi(api_client)
        try:
            # Step 3. Calling getCurrentUser on Authentication API logs you in if the user isn't already logged in.
            current_user = auth_api.get_current_user()
        except UnauthorizedException as e:
            if e.status == 200:
                if "Email 2 Factor Authentication" in e.reason:
                    # Step 3.5. Calling email verify2fa if the account has 2FA disabled
                    auth_api.verify2_fa_email_code(two_factor_email_code=TwoFactorEmailCode(input("Email 2FA Code: ")))
                elif "2 Factor Authentication" in e.reason:
                    # Step 3.5. Calling verify2fa if the account has 2FA enabled
                    auth_api.verify2_fa(two_factor_auth_code=TwoFactorAuthCode(input("2FA Code: ")))
                    current_user = auth_api.get_current_user()
                else:
                    print("Exception when calling API: %s\n", e)
        except vrchatapi.ApiException as e:
            print("Exception when calling API: %s\n", e)
        #
        print("Logged in as:", current_user.display_name)
        
        while(True):
            try:
                time.sleep(10)
                notifications = notifications_api.NotificationsApi(api_client).get_notifications()
                for notification in notifications:
                    if notification.type == 'friendRequest':
                        notifications_api.NotificationsApi(api_client).accept_friend_request(notification.id)
                        print("accepted friend!")
                        if not filter(notification.sender_username):  
                            speak_text(f"thanks for friending me, {notification.sender_username}!")
                            send_chatbox(f"thanks for friending me, {notification.sender_username}!")
                        invitereq = CreateGroupInviteRequest(notification.sender_user_id, True)
                        groups_api.GroupsApi(api_client).create_group_invite("grp_ed3c9205-ab1c-4564-840d-526d188ab7bf", invitereq)
                
                
                
            except:
                print("notif error")

def check_emotes(response):
    global is_emoting
    emote_map = {
        ("point", "look", "!"): 3,
        ("wave", "hi ", "hello"): 1,
        ("clap", "congrat"): 2,
        ("cheer",): 4,
        ("dance",): 5,
        ("backflip", "flip"): 6,
        ("kick",): 7,
        ("die", "dead"): 8,
    }
    response = response.lower()
    for keys, emote_id in emote_map.items():
        if any(k in response for k in keys):
            is_emoting = True
            client.send_message("/avatar/parameters/VRCEmote", [emote_id])
            time.sleep(2)
            client.send_message("/avatar/parameters/VRCEmote", [0])
            break
    is_emoting = False

def check_commands(combined, prompt):
    global is_emoting, movement_paused
    is_emoting = True
    commands = {
        "forward": ("/input/MoveForward", 2.0),
        "backward": ("/input/MoveBackward", 2.0),
        "left": ("/input/LookLeft", 0.45),
        "right": ("/input/LookRight", 0.45),
    }
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(lambda addr, dur: (
                client.send_message(addr, [1]),
                time.sleep(dur),
                client.send_message(addr, [0])
            ), address, duration)
            for cmd, (address, duration) in commands.items()
            if cmd in prompt and not (cmd == "right" and "alright" in prompt)
        ]
        [f.result() for f in futures]

    if "pause" in prompt and "move" in prompt:
        movement_paused = True
    elif "unpause" in prompt and "move" in prompt:
        movement_paused = False
    elif "switch" in prompt and "model" in prompt:
        switch_model()
    is_emoting = False

def speak_text(text):
    global playback_number
    playback_number += 1
    send_chatbox("Generating Text to Speech...")
    filename = f"{playback_number}norm.mp3"
    engine.save_to_file(text.replace(":", " colon "), filename)
    engine.runAndWait()
    audio = AudioSegment.from_file(filename)
    audio = audio.speedup(playback_speed=1.15)
    output_file = f"{playback_number}.mp3"
    audio.export(output_file, format="mp3")
    mixer.music.load(output_file)
    mixer.music.play()

def send_chatbox(message):
    messagestring = f"{bot_title}\v{message}"
    if len(messagestring) > 131:
        messagestring = messagestring[:140] + "..."
    print(message)
    client.send_message("/chatbox/input", [messagestring, True, False])

def listen_microphone():
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        try:
            audio = recognizer.listen(source, timeout=1.5, phrase_time_limit=6)
            return recognizer.recognize_google(audio, language='en-US')
        except (sr.WaitTimeoutError, sr.UnknownValueError):
            print("Could not understand speech. Please talk clearly!")
        except sr.RequestError as e:
            print(f"Speech recognition request error: {e}")

def switch_model():
    global fail_count, current_model
    send_chatbox(f"Model#{current_model} failed. Switching...")
    fail_count = 0
    current_model += 1

def ask_huggingchat(prompt):
    return str(chatbot.chat(prompt))

def reset_needed(text):
    triggers = ["reset", "restart"]
    targets = ["box", "bot", "bbott", "bebop", "butt"]
    text = text.lower()
    return any(t in text for t in triggers) and any(t in text for t in targets)

def main():
    load_filter_list()
    mixer.init()
    print("Outputs:", devices.audio.get_audio_device_names(False))
    engine.setProperty('voice', engine.getProperty('voices')[1].id)
    send_chatbox("Starting up...")

    threading.Thread(target=move_thread, name="MovementThread", daemon=True).start()
    threading.Thread(target=api_thread, name="APIThread", daemon=True).start()

    startup_msg = "This is the lower-end version of Tiger-bee bot. Things will change. " + ask_huggingchat(".")
    speak_text(startup_msg)
    send_chatbox(startup_msg)

    while True:
        spoken = listen_microphone()
        if spoken and not is_filtered(spoken):
            send_chatbox(f"Thinking... Model#{current_model}\n'{chatbot.active_model}'\nPrompt: {spoken}")
            try:
                if reset_needed(spoken):
                    chatbot.new_conversation(modelIndex=current_model, system_prompt=credentials.SYSTEM_PROMPT, switch_to=True)
                response = ask_huggingchat(spoken)
                if not is_filtered(response):
                    if len(response) > 300 or "<assistant" in response:
                        chatbot.new_conversation(modelIndex=current_model, system_prompt=credentials.SYSTEM_PROMPT, switch_to=True)
                        send_chatbox("Response was invalid. Resetting conversation.")
                    else:
                        speak_text(response)
                        send_chatbox(response)
                        check_commands(spoken + response, spoken)
                        check_emotes(response)
                else:
                    send_chatbox("Response was filtered. Please try again.")
            except Exception as e:
                print("Chat failure:", e)
                chatbot.new_conversation(modelIndex=current_model, system_prompt=credentials.SYSTEM_PROMPT, switch_to=True)
                global fail_count
                fail_count += 1
                if fail_count > 2:
                    switch_model()

if __name__ == "__main__":
    main()
