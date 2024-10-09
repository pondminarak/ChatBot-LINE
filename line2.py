from neo4j import GraphDatabase
from flask import Flask, request, jsonify
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from sentence_transformers import SentenceTransformer, util
import numpy as np
import faiss  # Import FAISS for efficient similarity search
import json
import requests

# Load the sentence transformer model
model = SentenceTransformer('sentence-transformers/distiluse-base-multilingual-cased-v2')

# Neo4j connection details
URI = "neo4j://localhost"
AUTH = ("neo4j", "123456789")

def run_query(query, parameters=None):
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        driver.verify_connectivity()
        with driver.session() as session:
            result = session.run(query, parameters)
            return [record for record in result]
    driver.close()

cypher_query = '''
MATCH (n:Greeting) RETURN n.name as name, n.msg_reply as reply;
'''

# Retrieve greetings from the Neo4j database
greeting_corpus = []
results = run_query(cypher_query)
for record in results:
    greeting_corpus.append(record['name'])

# Ensure corpus is unique
greeting_corpus = list(set(greeting_corpus))
print(greeting_corpus)

# Encode the greeting corpus into vectors using the sentence transformer model
greeting_vecs = model.encode(greeting_corpus, convert_to_numpy=True, normalize_embeddings=True)

# Initialize FAISS index
d = greeting_vecs.shape[1]  # Dimension of vectors
index = faiss.IndexFlatL2(d)  # L2 distance index (cosine similarity can be used with normalization)
index.add(greeting_vecs)  # Add vectors to FAISS index

def compute_similar_faiss(sentence):
    # Encode the query sentence
    ask_vec = model.encode([sentence], convert_to_numpy=True, normalize_embeddings=True)
    # Search FAISS index for nearest neighbor
    D, I = index.search(ask_vec, 1)  # Return top 1 result
    return D[0][0], I[0][0]

def neo4j_search(neo_query):
    results = run_query(neo_query)
    for record in results:
        response_msg = record['reply']
    return response_msg

# Ollama API endpoint (assuming you're running Ollama locally)
OLLAMA_API_URL = "http://localhost:11434/api/generate"

headers = {
    "Content-Type": "application/json"
}

def llama_generate_response(prompt):
    # Prepare the request payload for the supachai/llama-3-typhoon-v1.5 model
    payload = {
        "model": "supachai/llama-3-typhoon-v1.5",  # Adjust model name as needed
        "prompt": prompt + "ตอบไม่เกิน20คำและเข้าใจ",
        "stream": False
    }

    # Send the POST request to the Ollama API
    response = requests.post(OLLAMA_API_URL, headers=headers, data=json.dumps(payload))

    # Check if the request was successful
    if response.status_code == 200:
        # Parse the response JSON
        response_data = response.text
        data = json.loads(response_data)
        decoded_text = data.get("response", "No response found.")
        return "นี้คือคำตอบเพิ่มเติมที่มีนอกเหนือจากคลังความรู้ของเรานะครับ : " + decoded_text
    else:
        # Handle errors
        print(f"Failed to get a response: {response.status_code}, {response.text}")
        return "Error occurred while generating response."

def compute_response(sentence):
    score, index = compute_similar_faiss(sentence)
    if score > 0.5:
        # Use the new API-based method to generate a response
        prompt = f"คำถาม: {sentence}\nคำตอบ:"
        my_msg = llama_generate_response(prompt)
    else:
        Match_greeting = greeting_corpus[index]
        My_cypher = f"MATCH (n:Greeting) WHERE n.name = '{Match_greeting}' RETURN n.msg_reply as reply"
        my_msg = neo4j_search(My_cypher)
    print(my_msg)
    return my_msg

app = Flask(__name__)

@app.route("/", methods=['POST'])
def linebot():
    body = request.get_data(as_text=True)
    try:
        json_data = json.loads(body)
        access_token = 'nb7Lc36ImomAFYsKek9mtegv/DhVtYayaUksY3vxuFtGLXONd3zOmL+eLNKlO8HqOXb4a0/StXwS8AfZNpp5p+hjSk2wJzo/cpDtnG/SQNaSSudV4p78otUOIb042B9fXDW8nMyDC5mj7OCEQgN8JwdB04t89/1O/w1cDnyilFU='
        secret = '5280c53da8243d3e54a55d3aa4c9caa7'
        line_bot_api = LineBotApi(access_token)
        handler = WebhookHandler(secret)
        signature = request.headers['X-Line-Signature']
        handler.handle(body, signature)
        msg = json_data['events'][0]['message']['text']
        tk = json_data['events'][0]['replyToken']
        response_msg = compute_response(msg)
        line_bot_api.reply_message(tk, TextSendMessage(text=response_msg))
        print(msg, tk)
    except Exception as e:
        print(body)
        print(f"Error: {e}")
    return 'OK'

if __name__ == '__main__':
    app.run(port=5000)
