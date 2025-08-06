import os
import re
import telebot
import logging
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from bson import ObjectId
from dotenv import load_dotenv

# ตั้งค่า Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# โหลด Environment Variables
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

# สร้าง Bot
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# ลบ Webhook เพื่อใช้ Polling
try:
    bot.remove_webhook()
    logger.info("Webhook removed successfully")
except Exception as e:
    logger.error(f"Failed to remove webhook: {e}")

# เชื่อมต่อ MongoDB
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    client.admin.command('ping')  # ทดสอบการเชื่อมต่อ
    logger.info("Connected to MongoDB successfully")
    db = client["stock-management"]
    products_collection = db["products"]
    lots_collection = db["lots"]
    warehouse_collection = db["warehouses"]  # เปลี่ยนจาก warehouse เป็น warehouses
    # ตรวจสอบคอลเลคชัน
    collections = db.list_collection_names()
    logger.info(f"Collections in database: {collections}")
except ConnectionFailure as e:
    logger.error(f"MongoDB connection failed: {e}")
    raise
except OperationFailure as e:
    logger.error(f"MongoDB operation failed: {e}")
    raise
except Exception as e:
    logger.error(f"Unexpected error during MongoDB connection: {e}")
    raise

# ฟังก์ชันสำหรับคำสั่ง /start และ /help
@bot.message_handler(commands=['start', 'help'])
def handle_start_help(message):
    help_text = (
        "សូម​បញ្ចូល​លេខកូដ​ផលិតផល​ដែល​អ្នក​ចង់​ដឹង\n"
        "ហាម​ដក​ឃ្លា ឬ​អក្សរ​តូច\n"
        "ឧទាហរណ៍៖ 1015KH"
    )
    bot.reply_to(message, help_text)

# ฟังก์ชันสำหรับจัดการข้อความ (รหัสสินค้า)
@bot.message_handler(content_types=['text'])
def handle_message(message):
    try:
        product_code = message.text.strip()
        logger.info(f"Received product code: {product_code}")
        
        # ตรวจสอบว่ารหัสสินค้าถูกต้อง (XXXXKH)
        if not re.match(r'^\d{4}KH$', product_code, re.IGNORECASE):
            bot.reply_to(message, "សូមបញ្ចូលលេខកូដផលិតផលឲ្យបានត្រឹមត្រូវ (ឧទាហរណ៍: 1015KH)")
            return
        
        # ค้นหาสินค้าจากรหัส
        product = products_collection.find_one({"productCode": product_code})
        if not product:
            logger.warning(f"No product found for code: {product_code}")
            # ตรวจสอบจำนวนเอกสารในคอลเลคชัน products
            product_count = products_collection.count_documents({})
            logger.info(f"Total products in collection: {product_count}")
            # แสดงตัวอย่างข้อมูลใน products (ไม่เกิน 5 รายการ)
            sample_products = list(products_collection.find().limit(5))
            logger.info(f"Sample products: {[p['productCode'] for p in sample_products]}")
            bot.reply_to(message, f"រកមិនឃើញលេខកូដ {product_code} ផលិតផលនេះឡើយ")
            return

        product_id = ObjectId(product["_id"])  # แปลงเป็น ObjectId
        product_name = product["name"]
        logger.info(f"Found product: {product_code} - {product_name} (ID: {product_id})")

        # ค้นหา Lot ที่เกี่ยวข้องและรวม qtyOnHand ตาม Warehouse
        pipeline = [
            {"$match": {"productId": product_id, "status": "active"}},
            {
                "$group": {
                    "_id": "$warehouse",
                    "total_qty": {"$sum": "$qtyOnHand"}
                }
            },
            {
                "$lookup": {
                    "from": "warehouses",  # เปลี่ยนจาก warehouse เป็น warehouses
                    "localField": "_id",
                    "foreignField": "_id",
                    "as": "warehouse_info"
                }
            },
            {"$unwind": "$warehouse_info"},
            {"$match": {"total_qty": {"$gt": 0}}},  # เฉพาะ Warehouse ที่มีสต็อก
            {
                "$project": {
                    "warehouse_name": "$warehouse_info.name",
                    "total_qty": 1,
                    "_id": 0
                }
            }
        ]

        results = list(lots_collection.aggregate(pipeline))
        logger.info(f"Aggregation results for product {product_code}: {results}")

        if not results:
            logger.warning(f"No stock found for product: {product_code}")
            bot.reply_to(message, f"រកមិនឃើញលេខកូដ {product_code} ផលិតផលនេះឡើយ")
            return

        # สร้างข้อความผลลัพธ์
        response = f"📦 Summary for {product_code} — {product_name}\n"
        for result in results:
            response += f"🏭 {result['warehouse_name']}\n   👉 {product_name} : {result['total_qty']} pcs\n"

        bot.reply_to(message, response)
        logger.info(f"Sent response for {product_code}")

    except Exception as e:
        logger.error(f"Error processing message: {e}")
        bot.reply_to(message, "ប្រព័ន្ធកំពុងជួបប្រទះបញ្ហា សូមព្យាយាមម្តងទៀត។")

# เริ่ม Bot
if __name__ == "__main__":
    logger.info("Starting bot polling")
    bot.polling(none_stop=True)