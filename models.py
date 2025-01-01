from datetime import datetime
from pydantic import BaseModel


class Call(BaseModel):
    id: str
    Caller: str
    Transcript: str
    Summary: str
    Start: datetime
    End: datetime
    Cost: float = 0.0
    CostBreakdown: dict = {}
    EndedReason: str = ""  # Reason why the call ended

    def length_in_seconds(self):
        return (self.End - self.Start).total_seconds()
