import os
import base64
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

DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
    print(f"Created directory: {DATA_DIR}")

# OpenAI API Function
async def get_openai_response(prompt):
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

async def process_image_with_gpt4o(image_path, caption=None):
    """Process image using GPT-4o Vision"""
    try:
        # Read the image file
        with open(image_path, "rb") as image_file:
            image_data = image_file.read()
            
        # Convert image to base64
        base64_image = base64.b64encode(image_data).decode('utf-8')
        
        prompt_text = caption if caption else "Describe this image in detail."

        # Call OpenAI API with the image
        response = openAI_client.responses.create(
            model="gpt-4o",
            tools=[{ "type": "web_search_preview" }],
            tool_choice="auto",
            input=[
                {
                    "role": "user",
                    "content": [
                        { "type": "input_text", "text": prompt_text },
                        {
                            "type": "input_image",
                            "image_url": f"data:image/jpeg;base64,{base64_image}",
                        },
                    ],
                }
            ],
        )
        
        # Delete the image file after processing
        try:
            os.remove(image_path)
            print(f"Deleted image file: {image_path}")
        except Exception as e:
            print(f"Error deleting image file {image_path}: {e}")
        
        return response.output_text
    except Exception as e:
        print(f"Error processing image with GPT-4o: {e}")
        
        # Try to delete the image file even if processing failed
        try:
            if os.path.exists(image_path):
                os.remove(image_path)
                print(f"Deleted image file after error: {image_path}")
        except Exception as delete_error:
            print(f"Error deleting image file after processing error: {delete_error}")
            
        return f"Sorry, I couldn't analyze this image. Error: {str(e)}"

async def generate_image_with_dalle(prompt, user_id):
    """Generate an image using DALL-E 3"""
    try:
        # Call OpenAI API to generate image
        response = openAI_client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="standard",
            n=1,
        )
        
        # Get the image URL
        image_url = response.data[0].url
        
        # Download the image
        import requests
        response = requests.get(image_url)
        
        if response.status_code == 200:
            # Save the image to a file
            image_path = os.path.join(DATA_DIR, f"dalle_{user_id}.jpg")
            with open(image_path, "wb") as f:
                f.write(response.content)
            
            return image_path
        else:
            raise Exception(f"Failed to download image: {response.status_code}")
    except Exception as e:
        print(f"Error generating images: {e}")
        return None


# Start and Main Menu
@bot.on(events.NewMessage(pattern='/start'))
async def start(event):
    buttons = [
        [Button.inline("➕ Create Agent", b"create_agent")],
        [Button.inline("📜 List Existing Agents", b"list_agents")],
        [Button.inline("🎨 Generate Image", b"generate_image")],
        [Button.inline("🔍 Analyze Image", b"analyze_image")]
    ]
    await event.respond(
        "👋 Welcome to the AI Chatbot Manager!\n\n"
        "You can use the **menu buttons** to interact with the bot:\n"
        "✅ **Create Agent** - Create a new chatbot\n"
        "✅ **List Existing Agents** - View your chatbots\n"
        "✅ **Generate Image** - Create images\n"
        "✅ **Analyze Image** - Analyze and describe images"
        buttons=buttons
    )

# /create Command
@bot.on(events.NewMessage(pattern='/create'))
async def create(event):
    user_id = event.sender_id
    users_collection.update_one({"_id": user_id}, {"$set": {"state": "creating_bot"}}, upsert=True)
    await event.respond("✏️ Send the name of your chatbot.")


# /image Command
@bot.on(events.NewMessage(pattern='/image'))
async def image(event):
    user_id = event.sender_id
    # Set user state to waiting for image prompt
    users_collection.update_one(
        {"_id": user_id}, 
        {"$set": {"state": "waiting_for_image_prompt"}}
    )
    await event.respond(
        "🎨 Please enter a detailed description of the image you want to generate.\n\n"
        "Be specific and creative with your description for best results!"
    )


# /list Command
@bot.on(events.NewMessage(pattern='/list'))
async def list_bots(event):
    user_id = event.sender_id
    bots = chatbots_collection.find({"owner": user_id})
    if chatbots_collection.count_documents({"owner": user_id}) == 0:
        await event.respond("❌ No chatbots found. Use /create to make one.")
        return
    bot_buttons = [[Button.inline(bot["name"], f"select_{bot['name']}")] for bot in bots]
    bot_buttons.append([Button.inline("🔙 Back", b"main_menu")])

    if bot_buttons:
        await event.respond("📜 Your chatbots:", buttons=bot_buttons)
    else:
        await event.respond("❌ No chatbots found. Use /create to make one.")
 
        
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
            
        elif data == "generate_image":
            # Set user state to waiting for image prompt
            users_collection.update_one(
                {"_id": user_id}, 
                {"$set": {"state": "waiting_for_image_prompt"}}
            )
            await event.respond(
                "🎨 Please enter a detailed description of the image you want to generate.\n\n"
                "Be specific and creative with your description for best results!"
            )
            
        elif data == "analyze_image":
            # Prompt user to upload an image for analysis
            users_collection.update_one(
                {"_id": user_id}, 
                {"$set": {"state": "waiting_for_image_analysis"}}
            )
            await event.respond(
                "🔍 Please upload an image you'd like me to analyze.\n\n"
                "You can also add a caption with specific questions about the image."
            )
            
        elif data == "analyze_photo":
            # Retrieve the pending image path from the user's data
            user_data = users_collection.find_one({"_id": user_id})
            image_path = user_data.get("pending_image")
            caption = user_data.get("image_caption")
            
            if image_path and os.path.exists(image_path):
                m = await event.respond("🔍 Analyzing your image... Please wait.")
                try:
                    # Process with GPT-4o including caption
                    analysis = await process_image_with_gpt4o(image_path, caption)
                    
                    # Send the analysis back to the user
                    await event.respond(analysis)
                    
                    # Clear the pending image data
                    users_collection.update_one(
                        {"_id": user_id}, 
                        {"$unset": {"pending_image": "", "image_caption": ""}}
                    )
                    
                except Exception as e:
                    print(f"Error processing image with GPT-4o: {e}")
                    await event.respond(f"Sorry, I couldn't analyze this image. Error: {str(e)}")
                finally:
                    await m.delete()  # Delete the processing message
            else:
                await event.respond("❌ No image found to analyze or the image file was deleted.")

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
        await start(event)

# Handle Messages (Create Bot & Chatting)
@bot.on(events.NewMessage)
async def handle_messages(event):
    user_id = event.sender_id
    await bot(SetTypingRequest(peer=user_id, action=SendMessageTypingAction()))

    
    if event.photo:
        try:
            caption = event.message.message if event.message.message else None
            # Create file path with user ID
            image_path = os.path.join(DATA_DIR, f"{user_id}.jpg")
            
            # Download the photo to the specified path
            await bot.download_media(event.photo, image_path)
            print(f"Downloaded photo from user {user_id} to {image_path}")
            
            # Store the image path and caption in the user's data
            users_collection.update_one(
                {"_id": user_id}, 
                {"$set": {"pending_image": image_path, "image_caption": caption}}
            )
            
            # Show the user a button to analyze the photo
            buttons = [[Button.inline("🔍 Analyze Photo", b"analyze_photo")]]
            await event.respond(
                "📸 Photo received! Click the button below to analyze it with AI.", 
                buttons=buttons
            )
            
        except Exception as e:
            print(f"Error handling photo from user {user_id}: {e}")
            await event.respond(f"Sorry, I encountered an error: {str(e)}")

        return
    
    text = event.message.text
    
    if text.startswith("/"):
        return
    if not text:
        return
    
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

        # User is sending an image generation prompt
        elif user_state == "waiting_for_image_prompt":
            m = await event.respond("🎨 Generating your image... Please wait.")
            try:
                # Generate image with DALL-E
                image_path = await generate_image_with_dalle(text, user_id)
                
                if image_path and os.path.exists(image_path):
                    # Send the generated image
                    await bot.send_file(
                        user_id, 
                        image_path, 
                        caption="Here's your generated image! 🎨"
                    )
                    
                    # Clean up the image file
                    try:
                        os.remove(image_path)
                    except Exception as e:
                        print(f"Error deleting image file: {e}")
                else:
                    await event.respond("Sorry, I couldn't generate the image. Please try again with a different prompt.")
                
                # Clear the user state
                users_collection.update_one({"_id": user_id}, {"$unset": {"state": ""}})
                
            except Exception as e:
                print(f"Error handling image generation: {e}")
                traceback.print_exc()
                await event.respond(f"Sorry, I encountered an error while generating your image: {str(e)}")
                users_collection.update_one({"_id": user_id}, {"$unset": {"state": ""}})
            finally:
                await m.delete()  # Delete the processing message
                
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
                ai_response = await get_openai_response(prompt)

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
