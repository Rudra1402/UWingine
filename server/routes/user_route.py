import sys
import os
from dotenv import load_dotenv
from typing import Optional, List
from fastapi import APIRouter, Body, HTTPException, status, Response
from pydantic import EmailStr
from bson import ObjectId
from pymongo.errors import PyMongoError, DuplicateKeyError
from models.user_model import UserModel, LoginModel, QueryRequestModel, UserResponseModel, ChatModel, DateChatModel, UserChatSession
from core.security import hash_password, verify_password
from database.connection import user_collection, chat_collection, date_chat_collection, user_chat_session_collection
from typing import Union
from datetime import datetime, timedelta, timezone
import jwt

load_dotenv()

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'llm')))
from llm_model_qna import main as MainChat
from llm_model_qna_dates import main as LLMDates

router = APIRouter()

def utc_now():
    return datetime.now(timezone.utc)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire_minutes = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 15))  # Default to 15 minutes if not set
    expire = utc_now() + (expires_delta or timedelta(minutes=expire_minutes))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, os.getenv("SECRET_KEY"), algorithm=os.getenv("ALGORITHM"))
    return encoded_jwt

@router.get("/")
async def root():
    return {"message": "Welcome to the API! The server is up and running."}

@router.post(
    "/signup/",
    response_description="Register a new user",
    response_model=UserModel,
    status_code=status.HTTP_201_CREATED,
    response_model_by_alias=False,
)
async def signup(user: UserModel = Body(...)):
    try:
        user.password = hash_password(user.password)
        new_user = await user_collection.insert_one(user.model_dump(by_alias=True, exclude=["id"]))
        created_user = await user_collection.find_one({"_id": new_user.inserted_id})

        if created_user:
            return UserModel(**created_user)
    except DuplicateKeyError as e:
        return {
            "status": "error",
            "message": "User already exists!"
        }
    except PyMongoError as e:
        return {
            "status": "error",
            "message": "Internal Server Error"
        }

@router.post(
    "/login/",
    response_description="User login",
    status_code=status.HTTP_200_OK,
)
async def login(login_data: LoginModel = Body(...), response: Response = None):
    try:
        user = await user_collection.find_one({"email": login_data.email})
        if user and verify_password(login_data.password, user["password"]):
            access_token = create_access_token(data={"user_id": str(user["_id"]), "email": user["email"]})
            response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
            return {
                "stat": "success",
                "message": "Login successful",
                "statusCode": 200,
                "access_token": access_token,
                "user_data": {
                    "id": str(user["_id"]),
                    "email": user["email"],
                    "first_name": user["first_name"],
                    "last_name": user["last_name"]
                }
            }
        return {
            "stat": "error",
            "message": "Invalid credentials",
        }
    except PyMongoError as e:
        return {
            "stat": "error",
            "message": "Failed to login due to a server error.",
            "details": str(e)
        }

@router.get(
    "/users/{id}",
    response_description="Get a single user",
    response_model=UserResponseModel,
    response_model_by_alias=False,
)
async def show_user(id: str):
    try:
        user = await user_collection.find_one({"_id": ObjectId(id)})
        if user is not None:
            return {"stat": "success", "statusCode": 200, "data": user}
        return {
            "stat": "error",
            "message": f"User {id} not found",
        }
    except Exception as e:
        if isinstance(e, PyMongoError):
            return {
                "stat": "error",
                "message": "Failed to retrieve user due to a server error.",
                "details": str(e)
            }
        else:
            return {
                "stat": "error",
                "message": "Invalid ID format",
                "details": str(e)
            }

@router.delete("/users/{id}", response_description="Delete a user")
async def delete_user(id: str):
    try:
        delete_result = await user_collection.delete_one({"_id": ObjectId(id)})
        if delete_result.deleted_count == 1:
            return {"stat": "success", "message": "User deleted successfully"}
        return {
            "stat": "error",
            "message": f"User {id} not found",
        }
    except Exception as e:
        if isinstance(e, PyMongoError):
            return {
                "stat": "error",
                "message": "Failed to delete user due to a server error.",
                "details": str(e)
            }
        else:
            return {
                "stat": "error",
                "message": "Invalid ID format",
                "details": str(e)
            }

@router.post(
    "/chat/",
    response_description="Process user query",
    status_code=status.HTTP_200_OK
)
async def process_query(query_request: QueryRequestModel = Body(...), response: Response = None):
    try:
        user = await user_collection.find_one({"_id": ObjectId(query_request.thread_id)})
        d = MainChat(thread_id=query_request.thread_id, question=query_request.question)

        if not d or 'answer' not in d or d['answer'] is None:
            raise ValueError("The main function returned an invalid response")

        # Extract and format references from LLM response
        source_pages = d.get('source_pdf_pages', {})
        source_links = d.get('source_pdf_links', {})

        # Construct the references list
        references = [
            {
                "title": title,
                "link": source_links.get(title, ""),
                "pages": list(map(int, source_pages.get(title, [])))  # Ensure pages are stored as integers
            }
            for title in source_pages if title in source_links  # Only add if both page and link exist
        ]

        if user:
            chat_data = ChatModel(
                user_id=str(query_request.thread_id),
                role=user["user_type"],
                session_id=query_request.session_id,
                prompt=query_request.question,
                answer=d['answer'],
                references=references
            )

            await chat_collection.insert_one(chat_data.model_dump(by_alias=True, exclude=["id"]))

        result = {
            "message": f"Query '{d['answer']}' has been processed for user!",
            "result": d
        }
        
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while processing the query: {str(e)}"
        )
# Calling this API while creating new chat first time
@router.post("/chat/session/start", response_model=UserChatSession, status_code=status.HTTP_201_CREATED)
async def start_chat_session(user_id: str = Body(..., embed=True)):
    try:
        # Generate a new unique session ID
        session_id = str(ObjectId())
        
        # Create a new session object with the provided user ID and generated session ID
        new_session = UserChatSession(
            user_id= user_id,
            session_id=session_id,
            started_at=utc_now()
        )
        
        # Convert the Pydantic model to a dictionary for insertion into MongoDB
        session_dict = new_session.dict(by_alias=True)
        
        # Insert the new session into the MongoDB collection asynchronously
        insert_result = await user_chat_session_collection.insert_one(session_dict)
        
        # Retrieve the newly created session from MongoDB to return it in the response
        created_session = await user_chat_session_collection.find_one({"_id": insert_result.inserted_id})
        
        # Return the session data as per the Pydantic model
        return UserChatSession(**created_session)
    except Exception as e:
        # If an error occurs, raise an HTTPException with a 500 status code
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    
from bson import ObjectId

# /Calls this API to get total chats for logged-In user
@router.get("/sessions/{user_id}", response_model=List[UserChatSession])
async def get_sessions(user_id: str):
    documents = await user_chat_session_collection.find({"user_id": user_id}).to_list(length=100)
    sessions = [
        UserChatSession(
            id=str(session.get('_id')),
            user_id=str(session['user_id']),
            session_id=str(session['session_id']),
            started_at=session.get('started_at'),
            ended_at=session.get('ended_at')
        ) for session in documents
    ]
    return sessions


@router.post(
    "/datechat/",
    response_description="Process user's dates query",
    status_code=status.HTTP_200_OK
)
async def process_date_chat_query(query_request: QueryRequestModel = Body(...), response: Response = None):
    try:
        user = await user_collection.find_one({"_id": ObjectId(query_request.thread_id)})
        d = LLMDates(thread_id=query_request.thread_id, question=query_request.question)

        if not d or 'answer' not in d or d['answer'] is None:
            raise ValueError("The mainw function returned an invalid response")

        if user:
            date_chat_data = DateChatModel(
                user_id=str(query_request.thread_id),
                role=user["user_type"],
                prompt=query_request.question,
                answer=d['answer'],
            )
            await date_chat_collection.insert_one(date_chat_data.model_dump(by_alias=True, exclude=["id"]))

        result = {
            "message": f"Query '{d['answer']}' has been processed for user!",
            "result": d
        }
        
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while processing the query: {str(e)}"
        )

@router.get("/chat/session/history/{session_id}", description="Retrieve chat history for a user")
async def get_chat_history(session_id: str):
    try:
        cursor = chat_collection.find({"session_id": session_id})
        chat_records = await cursor.to_list(length=None)
        
        if chat_records is None:
            return []
    
        history = [
            {
                **record,
                "_id": str(record["_id"]),
                "user_id": str(record["user_id"])
            }
            for record in chat_records
        ]
        
        return {"status": "success", "data":history}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while retrieving chat history: {str(e)}"
        )
    
@router.get("/chat/datehistory/{thread_id}", description="Retrieve chat history for a user")
async def get_chat_history(thread_id: str):
    try:
        cursor = date_chat_collection.find({"user_id": thread_id})
        chat_records = await cursor.to_list(length=None)
        
        if chat_records is None:
            return []
    
        history = [
            {
                **record,
                "_id": str(record["_id"]),
                "user_id": str(record["user_id"])
            }
            for record in chat_records
        ]
        
        return {"status": "success", "data":history}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while retrieving chat history: {str(e)}"
        )