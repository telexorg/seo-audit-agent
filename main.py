import os, httpx
from pprint import pprint
import uvicorn, json
from uuid import uuid4
from fastapi import FastAPI, Request, status, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
from services import AgentService
import lxml

from a2a.types import (
    AgentCard,
    AgentCapabilities,
    AgentSkill,
    AgentProvider
)
import a2a.types as a2a_types



load_dotenv()

TELEX_API_KEY = os.getenv('TELEX_API_KEY')
TELEX_API_URL = os.getenv('TELEX_API_URL')

app = FastAPI()


@app.get("/", response_class=HTMLResponse)
def read_root():
    return '<p style="font-size:30px">Web Scraper agent</p>'


@app.get("/.well-known/agent.json")
def get_agent_card(request: Request):
    external_base = request.headers.get("x-external-base-url", "")
    current_base_url = str(request.base_url).rstrip("/") + external_base

    capabilities = AgentCapabilities(pushNotifications=True)

    skills = AgentSkill(
        id= "seo-audit",
        name= "SEO Auditing for webpages",
        description= "Audits Webpages for SEO issues",
        inputModes= ["text"],
        outputModes= ["text"],
        tags=["seo", "seo-audit"]
    )

    provider = AgentProvider(
       organization="Telex", url="https://telex.im"
    )

    agent_card = AgentCard(
        name='SEO Audit Agent',
        description='Audits Webpages for SEO issues',
        url=current_base_url,
        version='1.0.0',
        defaultInputModes=["text/plain"],
        defaultOutputModes=["text/plain"],
        capabilities=capabilities,
        skills=[skills],
        provider=provider,
        documentationUrl=f"{current_base_url}/docs"
    )

    return agent_card


async def handle_task(message:str, request_id, user_id:str, task_id: str, webhook_url: str, api_key: str, context_id: str):

  data = await AgentService.audit_page_with_ai(url=message, api_key=api_key)

  parts = a2a_types.TextPart(text=data)

  message = a2a_types.Message(messageId=uuid4().hex, role=a2a_types.Role.agent, parts=[parts])

  artifacts = a2a_types.Artifact(artifactId=uuid4().hex, parts=[parts])

  task = a2a_types.Task(
    id = task_id,
    contextId= context_id,
    status =  a2a_types.TaskStatus(
      state=a2a_types.TaskState.completed, 
      message=a2a_types.Message(messageId=uuid4().hex, role=a2a_types.Role.agent, parts=[a2a_types.TextPart(text="Success!")])
    ),
    artifacts = [artifacts]
  )

  webhook_response = a2a_types.SendMessageSuccessResponse(
      id=request_id,
      result=task
  )

  pprint(webhook_response.model_dump(exclude_none=True))


  async with httpx.AsyncClient() as client:
    headers = {"X-TELEX-API-KEY": api_key}
    is_sent = await client.post(webhook_url, headers=headers,  json=webhook_response.model_dump(exclude_none=True, mode="json"))
    pprint(is_sent.json())

  print("background done")
  return 



@app.post("/")
async def handle_request(request: Request, background_tasks: BackgroundTasks):
  try:
    body = await request.json()

  except json.JSONDecodeError as e:
    error = a2a_types.JSONParseError(
      data = str(e)
    )
    response = a2a_types.JSONRPCErrorResponse(
       error=error
    )

  request_id = body.get("id")
  user_id = body["params"]["message"]["metadata"].get("telex_user_id", None)  
  org_id = body["params"]["message"]["metadata"].get("org_id", None)  
  webhook_url = body["params"]["configuration"]["pushNotificationConfig"]["url"]
  api_key = body["params"]["configuration"]["pushNotificationConfig"]["authentication"].get("credentials", TELEX_API_KEY)

  message_parts = body["params"]["message"]["parts"]

  if not message_parts:
    raise HTTPException(
      status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
      detail="Message cannot be empty."
    )
  
  context_id = uuid4().hex

  new_task = a2a_types.Task(
    id = uuid4().hex,
    contextId=context_id,
    status =  a2a_types.TaskStatus(
      state=a2a_types.TaskState.submitted, 
      message=a2a_types.Message(messageId=uuid4().hex, role=a2a_types.Role.agent, parts=[a2a_types.TextPart(text="In progress")])
    )
  )

  incoming_message: a2a_types.Part = message_parts[0]

  print(incoming_message, "message")

  text_message = incoming_message.get("text", None)

  if not text_message:
    raise HTTPException(
      status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
      detail="Message text cannot be empty."
    )

  background_tasks.add_task(handle_task, text_message, request_id, user_id, new_task.id, webhook_url, api_key, context_id)

  response = a2a_types.JSONRPCResponse(
      id=request_id,
      result=new_task
  )

  response = response.model_dump(exclude_none=True)
  pprint(response)
  return response


if __name__ == "__main__":
    port = int(os.getenv("PORT", 4000))
    uvicorn.run("main:app", host="127.0.0.1", port=port, reload=True)
