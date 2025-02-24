from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    MessageEvent,
    PostbackEvent,
    JoinEvent,
    LeaveEvent,
    TextMessageContent
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    QuickReply,
    QuickReplyItem,
    TextMessage,
    PostbackAction,
    TemplateMessage,
    ConfirmTemplate,
    FlexMessage,
    FlexBubble,
    FlexImage,
    FlexBox,
    FlexText,
    FlexIcon,
    FlexButton,
    FlexSeparator,
    FlexContainer,
    DatetimePickerAction
)
from pymongo.mongo_client import MongoClient
import os

app = Flask(__name__)

mongodb_client = MongoClient(os.getenv("MONGODB_URI"))
try:
    db = mongodb_client.GroupLogBot
    print("成功連結到資料庫")
except Exception as e:
    print("連結失敗")
    print(e)

CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
MONGODB_URI = os.getenv("MONGODB_URI")

line_handler = WebhookHandler(CHANNEL_SECRET)

configuration = Configuration(
    access_token=CHANNEL_ACCESS_TOKEN
)

@app.route("/callback", methods=['POST'])
def callback():
    # 取得 X-Line-Signature header 的值
    signature = request.headers.get('X-Line-Signature')
    # 取得 request body
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # 處理 webhook 內容
    try:
        line_handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@line_handler.add(JoinEvent)
def handle_join(event):
    group_id = event.source.group_id
    insert_data("GroupInfo", {"group_id": group_id, "active": True, "timestamp": event.timestamp, "members": []})
    insert_data("EventLog", {"group_id": group_id, "timestamp": event.timestamp, "funcs": ""})
    reply_line_message(event, [TextMessage(text="你好我是紀錄機器人")])
    return

@line_handler.add(LeaveEvent)
def handle_leave(event):
    group_id = event.source.group_id
    delete_data("GroupInfo", {"group_id": group_id})
    delete_data("EventLog", {"group_id": group_id})
    delete_data("Calendar", {"group_id": group_id})
    reply_line_message(event, [TextMessage(text="掰掰")])
    return

@line_handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    message = event.message.text
    if message == "紀錄":
        if get_cols("EventLog").find_one({"group_id": event.source.group_id})["funcs"] == "":
            update_data("EventLog", {"group_id": event.source.group_id}, {"$set": {"timestamp": event.timestamp, "funcs": "funcs_menu"}})
            generate_quick_reply_response(event, "請選擇以下功能", [
                QuickReplyItem(
                    action=DatetimePickerAction(
                        label="新增紀錄",
                        data="select",
                        mode="date"
                    )
                ),
                QuickReplyItem(
                    action=PostbackAction(
                        label="查詢紀錄",
                        data="get"
                    )
                ),
                QuickReplyItem(
                    action=PostbackAction(
                        label="退出",
                        data="exit"
                    )
                )
            ])
            return
        else:
            update_data("EventLog", {"group_id": event.source.group_id}, {"$set": {"timestamp": event.timestamp, "funcs": ""}})
            reply_line_message(event, [TextMessage(text="請重新開始記錄")])
            return
    else:
        # 處於建立紀錄流程中
        if get_cols("EventLog").find_one({"group_id": event.source.group_id})["funcs"] == "create_record":
            record_date = get_cols("EventLog").find_one({"group_id": event.source.group_id}).get("date")
            if record_date:
                insert_data("Calendar", {
                    "group_id": event.source.group_id,
                    "user_id": event.source.user_id,
                    "timestamp": event.timestamp,
                    "record_date": record_date,
                    "content": message
                })
                update_data("EventLog", {"group_id": event.source.group_id}, {"$set": {"timestamp": event.timestamp, "funcs": ""}})
                reply_line_message(event, [TextMessage(text="紀錄完成")])
                return
            else:
                update_data("EventLog", {"group_id": event.source.group_id}, {"$set": {"timestamp": event.timestamp, "funcs": ""}})
                reply_line_message(event, [TextMessage(text="未正確選擇時間，請重新開始記錄")])
                return
        else:
            # 其他狀況暫不處理
            update_data("EventLog", {"group_id": event.source.group_id}, {"$set": {"timestamp": event.timestamp, "funcs": ""}})
            return

@line_handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    if data == "select":
        record = get_cols("EventLog").find_one({"group_id": event.source.group_id})
        if record and record.get("funcs") == "funcs_menu":
            update_data("EventLog", {"group_id": event.source.group_id}, {"$set": {
                "timestamp": event.timestamp,
                "funcs": "create_record",
                "date": event.postback.params["date"]
            }})
            reply_line_message(event, [
                TextMessage(text=f"已選擇日期: {event.postback.params['date']}"),
                TextMessage(text="請輸入內容")
            ])
            return
        else:
            update_data("EventLog", {"group_id": event.source.group_id}, {"$set": {"timestamp": event.timestamp, "funcs": ""}})
            reply_line_message(event, [TextMessage(text="未正確選擇功能，請重新開始記錄")])
            return

    if data == "get":
        records = get_cols("Calendar").find_one({"group_id": event.source.group_id})
        if records:
            template_message = TemplateMessage(
                alt_text=f"{records.get('record_date')} 的紀錄",
                template=ConfirmTemplate(
                    text=f"日期: {records.get('record_date')}\n內容: {records.get('content')}",
                    actions=[
                        PostbackAction(
                            label="查看下一筆",
                            data="next"
                        ),
                        PostbackAction(
                            label="退出",
                            data="exit"
                        )
                    ]
                )
            )
            reply_line_message(event, [template_message])
        else:
            reply_line_message(event, [TextMessage(text="無紀錄")])
        return

    if data == "exit":
        update_data("EventLog", {"group_id": event.source.group_id}, {"$set": {"timestamp": event.timestamp, "funcs": ""}})
        reply_line_message(event, [TextMessage(text="退出紀錄")])
        return
    else:
        update_data("EventLog", {"group_id": event.source.group_id}, {"$set": {"timestamp": event.timestamp, "funcs": ""}})
        return

def generate_quick_reply_response(event, message, items):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(
                        text=message,
                        quick_reply=QuickReply(
                            items=items
                        )
                    )
                ]
            )
        )

def reply_line_message(event, messages):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=messages
            )
        )

def push_line_message(group_id, messages):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.push_message(
            PushMessageRequest(
                to=group_id,
                messages=messages
            )
        )

def get_cols(collection):
    return db[collection]

def find_all_data(collection):
    return get_cols(collection).find()

def insert_data(collection, data):
    get_cols(collection).insert_one(data)

def update_data(collection, query, data):
    get_cols(collection).update_one(query, data)

def delete_data(collection, data):
    get_cols(collection).delete_one(data)

if __name__ == "__main__":
    app.run()