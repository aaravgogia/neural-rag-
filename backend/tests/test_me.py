import os, sys
import httpx, pytest, pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.api.routes import me
from app.api.routes.auth import get_current_user
from app.models.database import AuditLog, Base, ChatMessage, ChatSession, Document, TokenUsage, User, Workspace, WorkspaceMember, get_db

@pytest_asyncio.fixture
async def client(tmp_path):
    engine=create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'me.db'}"); maker=async_sessionmaker(engine,expire_on_commit=False)
    async with engine.begin() as c: await c.run_sync(Base.metadata.create_all)
    u=User(id='u',email='u@example.com',name='U'); other=User(id='o',email='o@example.com',name='O'); ws=Workspace(id='w',name='W',owner_id='o')
    async with maker() as db:
        db.add_all([u,other,ws,WorkspaceMember(workspace_id='w',user_id='u',role='viewer'),WorkspaceMember(workspace_id='w',user_id='o',role='owner'),Document(id='d',user_id='u',workspace_id='w',filename='mine.txt',file_size=1,file_type='txt'),Document(id='od',user_id='o',workspace_id='w',filename='other.txt',file_size=1,file_type='txt'),ChatSession(id='s',user_id='u',workspace_id='w'),ChatSession(id='os',user_id='o',workspace_id='w'),ChatMessage(session_id='s',user_id='u',role='human',content='mine'),ChatMessage(session_id='os',user_id='o',role='human',content='other'),AuditLog(user_id='u',query_text='mine'),AuditLog(user_id='o',query_text='other'),TokenUsage(user_id='u',session_id='s',prompt_tokens=1,completion_tokens=1)])
        await db.commit()
    app=FastAPI(); app.include_router(me.router,prefix='/api/v1'); selected={'u':u}
    async def odb():
        async with maker() as db: yield db
    async def ou(): return selected['u']
    app.dependency_overrides[get_db]=odb; app.dependency_overrides[get_current_user]=ou
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://x') as c: yield c,maker,selected,u,other
    await engine.dispose()

@pytest.mark.asyncio
async def test_export_and_confirmed_delete(client):
    c,maker,selected,u,other=client; data=(await c.get('/api/v1/me/export')).json()
    assert [d['id'] for d in data['documents']]==['d'] and data['conversations'][0]['messages'][0]['content']=='mine' and data['audit_logs'][0]['query_text']=='mine'
    assert (await c.delete('/api/v1/me')).status_code==422
    token=(await c.post('/api/v1/me/delete-confirmation')).json()['confirmation_token']; assert (await c.delete('/api/v1/me',params={'confirmation_token':token})).status_code==200
    async with maker() as db:
        assert (await db.execute(select(User).where(User.id=='u'))).scalar_one_or_none() is None
        assert not (await db.execute(select(Document).where(Document.user_id=='u'))).scalars().all()
        assert not (await db.execute(select(ChatMessage).where(ChatMessage.user_id=='u'))).scalars().all()
        assert not (await db.execute(select(TokenUsage).where(TokenUsage.user_id=='u'))).scalars().all()

@pytest.mark.asyncio
async def test_sole_owner_is_blocked(client):
    c,maker,selected,u,other=client
    async with maker() as db: db.add(Workspace(id='owned',name='Owned',owner_id='u')); await db.commit()
    token=(await c.post('/api/v1/me/delete-confirmation')).json()['confirmation_token']
    assert (await c.delete('/api/v1/me',params={'confirmation_token':token})).status_code==409
