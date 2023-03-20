from typing import Dict, List, TypedDict
import re

from fastapi import FastAPI
from pydantic import BaseModel

from s3 import upload
from env import settings

from prompts.error import ERROR_PROMPT
from agents.builder import AgentBuilder
from tools.base import BaseToolSet
from tools.cpu import (
    Terminal,
    RequestsGet,
    WineDB,
    ExitConversation,
)
from tools.gpu import (
    ImageEditing,
    InstructPix2Pix,
    Text2Image,
    VisualQuestionAnswering,
)
from handlers.base import BaseHandler, FileType
from handlers.image import ImageCaptioning
from handlers.dataframe import CsvToDataframe

app = FastAPI()

toolsets: List[BaseToolSet] = [
    Terminal(),
    RequestsGet(),
    ExitConversation(),
    Text2Image("cuda"),
    ImageEditing("cuda"),
    InstructPix2Pix("cuda"),
    VisualQuestionAnswering("cuda"),
]

handlers: Dict[FileType, BaseHandler] = {
    FileType.IMAGE: ImageCaptioning("cuda"),
    FileType.DATAFRAME: CsvToDataframe(),
}

if settings["WINEDB_HOST"] and settings["WINEDB_PASSWORD"]:
    toolsets.append(WineDB())

agent, handler = AgentBuilder.get_agent_and_handler(
    toolsets=toolsets, handlers=handlers
)


class Request(BaseModel):
    key: str
    query: str
    files: List[str]


class Response(TypedDict):
    response: str
    files: List[str]


@app.get("/")
async def index():
    return {"message": f"Hello World. I'm {settings['BOT_NAME']}."}


@app.post("/command")
async def command(request: Request) -> Response:
    query = request.query
    files = request.files
    key = request.key

    print("=============== Running =============")
    print("Inputs:", query, files)
    # TODO - add state to memory (use key)

    print("======>Previous memory:\n %s" % agent.memory)

    promptedQuery = "\n".join([handler.handle(file) for file in files])
    promptedQuery += query
    print("======>Prompted Text:\n %s" % promptedQuery)

    try:
        res = agent({"input": promptedQuery})
    except Exception as e:
        try:
            res = agent(
                {
                    "input": ERROR_PROMPT.format(promptedQuery=promptedQuery, e=str(e)),
                }
            )
        except Exception as e:
            return {"response": str(e), "files": []}

    images = re.findall("(image/\S*png)", res["output"])
    dataframes = re.findall("(dataframe/\S*csv)", res["output"])

    return {
        "response": res["output"],
        "files": [upload(image) for image in images]
        + [upload(dataframe) for dataframe in dataframes],
    }
