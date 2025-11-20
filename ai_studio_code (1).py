from fastapi import FastAPI, Request, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from database import SessionLocal, SupportProgram, init_db
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# DB 세션
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# [기능 1 & 3] 실제 크롤링 + 데이터 가공
def crawl_ksepa_real(db: Session):
    url = "https://www.socialenterprise.or.kr/news/notice/noticeList.do"
    base_url = "https://www.socialenterprise.or.kr/news/notice/noticeDetail.do?seq="
    
    # 봇 차단 방지 헤더
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        # SSL 인증서 무시 (verify=False)
        response = requests.get(url, headers=headers, verify=False)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 리스트 행(tr) 가져오기
        rows = soup.select(".tbl_list tbody tr")
        
        print(f"🔍 크롤링 시작: {len(rows)}개의 공고 발견")

        for row in rows:
            title_tag = row.select_one(".subject a")
            if not title_tag: continue
            
            title_text = title_tag.get_text(strip=True)
            
            # 이미 저장된 글이면 스킵 (중복 방지)
            if db.query(SupportProgram).filter(SupportProgram.title == title_text).first():
                continue

            # 링크 추출 (JS onclick="fn_view('1234')" 형태 파싱)
            onclick = title_tag.get("onclick", "")
            seq_match = re.search(r"\d+", onclick)
            real_link = base_url + seq_match.group() if seq_match else url
            
            # 날짜 추출 (4번째 td)
            date_td = row.select("td")[3]
            reg_date = date_td.get_text(strip=True) if date_td else datetime.now().strftime("%Y-%m-%d")

            # 카테고리 자동 분류
            cat = "기타"
            if "사회적" in title_text: cat = "사회적기업"
            elif "협동" in title_text: cat = "협동조합"
            elif "마을" in title_text: cat = "마을기업"
            elif "소셜" in title_text or "벤처" in title_text: cat = "소셜벤처"

            # DB 저장
            new_item = SupportProgram(
                title=title_text,
                category=cat,
                agency="한국사회적기업진흥원",
                reg_date=reg_date,
                link=real_link
            )
            db.add(new_item)
        
        db.commit()
        print("✅ 데이터 업데이트 완료")
        
    except Exception as e:
        print(f"❌ 크롤링 에러: {e}")

@app.on_event("startup")
def on_startup():
    init_db()

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, db: Session = Depends(get_db)):
    # 접속 시 크롤링 실행
    crawl_ksepa_real(db)
    
    # [기능 3] 정렬: 최신 등록순 (ID 역순)
    programs = db.query(SupportProgram).order_by(SupportProgram.id.desc()).all()
    
    # [기능 3] '신규' 배지 로직 (등록일이 7일 이내면 True)
    today = datetime.now()
    for p in programs:
        try:
            p_date = datetime.strptime(p.reg_date, "%Y-%m-%d")
            # 속성(is_new)을 객체에 임시로 추가
            p.is_new = (today - p_date).days <= 7
        except:
            p.is_new = False

    return templates.TemplateResponse("index.html", {"request": request, "programs": programs})

@app.get("/search")
async def search(keyword: str, request: Request, db: Session = Depends(get_db)):
    programs = db.query(SupportProgram).filter(SupportProgram.title.contains(keyword)).order_by(SupportProgram.id.desc()).all()
    # 검색 결과에도 배지 로직 적용 필요
    today = datetime.now()
    for p in programs:
        try:
            p_date = datetime.strptime(p.reg_date, "%Y-%m-%d")
            p.is_new = (today - p_date).days <= 7
        except:
            p.is_new = False
            
    return templates.TemplateResponse("index.html", {"request": request, "programs": programs})