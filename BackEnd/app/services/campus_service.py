from sqlalchemy.orm import Session
from app.models.DB_Table import Building

class CampusService :
    def search_location(self, db : Session, keyword : str) :
        result = db.query(Building).filter(Building.name.ilike(f"%{keyword}%")).first()  #ilike는 대소문자 구분 없이, 포함된 단어를 찾아줌.

        #검색 결과가 없을 때
        if not result:
            return {"msg" : f"'{keyword}'에 대한 위치를 찾을 수 없습니다. 정확한 건물명이나 학과를 입력해주세요."}
        
        #호수가 있는 경우와 없는 경우를 처리
        room_info = f"{result.room_no}호" if result.room_no else ""

        #검색 결과가 있을 시 최종 안내 메시지
        return {"msg" : f"[{result.facility_name}] 위치 안내 : {result.name}{room_info}에 위치해 있습니다."}