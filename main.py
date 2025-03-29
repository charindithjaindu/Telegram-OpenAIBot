import os
from openai import OpenAI
from telethon import TelegramClient, events, Button
from telethon.tl.functions.messages import SetTypingRequest
from telethon.tl.types import SendMessageTypingAction
from pymongo import MongoClient
from dotenv import load_dotenv
import traceback

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

# Setup MongoDB
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["telegram_bot"]
users_collection = db["users"]
chatbots_collection = db["chatbots"]

# Setup Telethon bot
bot = TelegramClient('bot', API_ID, API_HASH).start(bot_token=BOT_TOKEN)
openAI_client = OpenAI()


# OpenAI API Function
def get_openai_response(prompt):
    try:
        response = openAI_client.responses.create(
            model="gpt-4o",
            tools=[{ "type": "web_search_preview" }],
            tool_choice="auto",
            input=[{"role": "user", "content": prompt}]
        )
        return response.output_text
    except Exception as e:
        return f"Error: {str(e)}"

# Start and Main Menu
@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    buttons = [
        [Button.inline("➕ Create Agent", b"create_agent")],
        [Button.inline("📜 List Existing Agents", b"list_agents")]
    ]
    await event.respond(
        "👋 Welcome to the AI Chatbot Manager!\n\n"
        "You can use the **menu buttons** or type commands:\n"
        "✅ **/create** - Create a new chatbot\n"
        "✅ **/list** - View your chatbots\n"
        "✅ **/help** - Show help menu",
        buttons=buttons
    )

# /create Command
@bot.on(events.NewMessage(pattern='/create'))
async def create(event):
    user_id = event.sender_id
    users_collection.update_one({"_id": user_id}, {"$set": {"state": "creating_bot"}}, upsert=True)
    await event.respond("✏️ Send the name of your chatbot.")

# Handle Inline Buttons
@bot.on(events.CallbackQuery)
async def callback_handler(event):
    user_id = event.sender_id
    data = event.data.decode()

    try:
        if data == "create_agent":
            # Set user state to "creating_bot"
            users_collection.update_one({"_id": user_id}, {"$set": {"state": "creating_bot"}}, upsert=True)
            await event.respond("✏️ Send the name of your chatbot.")

        elif data == "list_agents":
            bots = chatbots_collection.find({"owner": user_id})
            bot_buttons = [[Button.inline(bot["name"], f"select_{bot['name']}")] for bot in bots]
            bot_buttons.append([Button.inline("🔙 Back", b"main_menu")])

            if bot_buttons:
                await event.respond("📜 Select a chatbot:", buttons=bot_buttons)
            else:
                await event.respond("❌ No chatbots found. Go back and create one.")

        elif data == "main_menu":
            await start(event)  # Return to the main menu

        elif data.startswith("select_"):
            bot_name = data.replace("select_", "")
            users_collection.update_one({"_id": user_id}, {"$set": {"selected_bot": bot_name}})

            buttons = [
                [Button.inline("✏️ Edit Instructions", b"edit_bot")],
                [Button.inline("🗑️ Delete Bot", b"delete_bot")],
                [Button.inline("💬 Chat with Bot", f"chat_{bot_name}")],
                [Button.inline("🔙 Back", b"list_agents")]
            ]
            await event.respond(f"🤖 Chatbot '{bot_name}' selected! Choose an action:", buttons=buttons)
            
        elif data == "edit_bot":
            selected_bot = users_collection.find_one({"_id": user_id}).get("selected_bot")
            if selected_bot:
                users_collection.update_one({"_id": user_id}, {"$set": {"state": "editing_bot"}})
                await event.respond(f"✏️ Send the new instructions for '{selected_bot}'.")

        elif data == "delete_bot":
            selected_bot = users_collection.find_one({"_id": user_id}).get("selected_bot")
            if selected_bot:
                chatbots_collection.delete_one({"owner": user_id, "name": selected_bot})
                users_collection.update_one({"_id": user_id}, {"$unset": {"selected_bot": ""}})
                await event.respond(f"🗑️ Chatbot '{selected_bot}' deleted successfully!")

        elif data.startswith("chat_"):
            bot_name = data.replace("chat_", "")
            users_collection.update_one({"_id": user_id}, {"$set": {"state": "chatting", "chatbot": bot_name}})
            await event.respond(f"🤖 Chatbot '{bot_name}' selected!\n\nType your message to chat.\nTo stop, send `/stop`.")

        elif data == "main_menu":
            await start(event)

    except:
        buttons = [
            [Button.inline("➕ Create Agent", b"create_agent")],
            [Button.inline("📜 List Existing Agents", b"list_agents")]
        ]
        await event.respond("👋 Welcome! Choose an option:", buttons=buttons)
        

# Handle Messages (Create Bot & Chatting)
@bot.on(events.NewMessage)
async def handle_messages(event):
    user_id = event.sender_id
    text = event.message.text
    await bot(SetTypingRequest(peer=user_id, action=SendMessageTypingAction()))
    
    try:
        # Get user state
        user_data = users_collection.find_one({"_id": user_id})
        user_state = user_data.get("state", "")

        # Step 1: User is sending chatbot name
        if user_state == "creating_bot":
            users_collection.update_one({"_id": user_id}, {"$set": {"bot_name": text, "state": "waiting_for_instructions"}})
            await event.respond("📜 Now send the chatbot's instructions.")

        # Step 2: User is sending chatbot instructions
        elif user_state == "waiting_for_instructions":
            bot_name = user_data["bot_name"]
            chatbots_collection.insert_one({
                "owner": user_id,
                "name": bot_name,
                "instructions": text,
                "messages": []
            })
            users_collection.update_one({"_id": user_id}, {"$unset": {"state": "", "bot_name": ""}})  # Clear state
            await event.respond(f"✅ Chatbot '{bot_name}' created successfully! Use the menu to chat.")

        elif user_state == "editing_bot":
            bot_name = user_data.get("selected_bot")
            if bot_name:
                chatbots_collection.update_one({"owner": user_id, "name": bot_name}, {"$set": {"instructions": text}})
                users_collection.update_one({"_id": user_id}, {"$unset": {"state": ""}})
                await event.respond(f"✅ Instructions for '{bot_name}' updated successfully!")

        # Step 3: User is chatting with a bot
        elif user_state == "chatting":
            bot_name = user_data.get("chatbot")
            if text == "/stop":
                users_collection.update_one({"_id": user_id}, {"$unset": {"state": "", "chatbot": ""}})
                await event.respond("🛑 Chat stopped. Use /start to go back to the menu.")
                return

            chatbot = chatbots_collection.find_one({"owner": user_id, "name": bot_name})
            if chatbot:
                prompt = f"{chatbot['instructions']}\nUser: {text}\nAI:"
                ai_response = get_openai_response(prompt)

                # Store conversation in MongoDB 
                chatbots_collection.update_one({"owner": user_id, "name": bot_name}, {
                    "$push": {"messages": {"user": text, "bot": ai_response}}
                })

                await event.respond(f"{bot_name}: {ai_response}", link_preview=False)
    except Exception as e:
        print(e)
        traceback.print_exc()
        buttons = [
            [Button.inline("➕ Create Agent", b"create_agent")],
            [Button.inline("📜 List Existing Agents", b"list_agents")]
        ]
        await event.respond("👋 Welcome! Choose an option:", buttons=buttons)

print("Bot started")
bot.run_until_disconnected()
