# IMSI school notice crawler

학교 공지 페이지를 크롤링한 뒤 텍스트를 청킹하고, 기존 BAAI embedding/Qdrant 저장 흐름으로 넣는 임시 코드입니다.

## 실행

`BackEnd` 폴더에서 가상환경을 활성화한 뒤 실행합니다.

```powershell
python -m app.imsi.ingest_webpage
```

다른 게시글을 넣고 싶으면 URL과 Qdrant payload의 source 값을 바꿔 실행합니다.

```powershell
python -m app.imsi.ingest_webpage `
  --url "https://tech.endicott.ac.kr/board/read.jsp?id=267227&code=tech0601" `
  --source "tech_notice_267227"
```

## 동작 흐름

1. `crawler.py`가 게시글 HTML에서 제목, 작성자, 작성일, 조회수, 본문, 첨부파일 링크를 추출합니다.
2. `ingest_webpage.py`가 문서 텍스트를 `split_by_length`로 청킹합니다.
3. 기존 `BaaiEmbedding`으로 임베딩합니다.
4. 기존 `QdrantVectorStore`로 `school_documents` 컬렉션에 upsert합니다.

