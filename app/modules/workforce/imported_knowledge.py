"""Published helpdesk knowledge and HR-managed drafts."""
from typing import Literal

from fastapi import Depends, HTTPException, Query, Response
from pydantic import Field, field_validator

from app.core.compatibility_routing import APIRouter
from app.data.database import get_db
from app.data.imported import find, table
from app.modules.workforce.imported_assets import admin, insert, now, rows
from app.modules.workforce.imported_leave import Input, output, staff
from app.modules.workforce.imported_organization import update

router = APIRouter(prefix='/api/ask-me', tags=['Helpdesk knowledge'])


class FAQInput(Input):
    question: str | None = Field(default=None, min_length=1, max_length=512)
    answer: str | None = Field(default=None, min_length=1, max_length=100000)
    isPublished: bool | None = Field(default=None, strict=True)
    sortOrder: int | None = Field(default=None, ge=-100000, le=100000)


@router.get('/faqs')
def faqs(includeDraft: str = '', user=Depends(staff), db=Depends(get_db)):
    include = includeDraft == '1' and user.role in ('admin', 'hr')
    records = rows(db, 'KnowledgeBaseFaq', order=table(db, 'KnowledgeBaseFaq').c.sortOrder)
    return output({'faqs': [row for row in records if include or row['isPublished']]})


@router.post('/faqs', status_code=201)
def add_faq(body: FAQInput, user=Depends(admin), db=Depends(get_db)):
    if not body.question or not body.answer:
        raise HTTPException(422, 'Enter both a question and an answer')
    return output({'faq': insert(db, 'KnowledgeBaseFaq', {'isPublished': True, 'sortOrder': 0, **body.model_dump(exclude_none=True)})})


@router.patch('/faqs/{id}')
def edit_faq(id: str, body: FAQInput, user=Depends(admin), db=Depends(get_db)):
    values = body.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(422, 'Provide a FAQ change')
    return output({'faq': update(db, 'KnowledgeBaseFaq', id, values)})


def delete_record(db, model, id):
    find(db, model, id, lock=True)
    tbl = table(db, model)
    db.execute(tbl.delete().where(tbl.c.id == id))
    return Response(status_code=204)


@router.delete('/faqs/{id}', status_code=204)
def delete_faq(id: str, user=Depends(admin), db=Depends(get_db)):
    return delete_record(db, 'KnowledgeBaseFaq', id)


class ArticleInput(Input):
    title: str = Field(min_length=1, max_length=512)
    excerpt: str = Field(min_length=1, max_length=20000)
    content: str = Field(min_length=1, max_length=500000)
    tag: Literal['HR', 'PAYROLL', 'IT', 'LEAVE', 'POLICY', 'FINANCE', 'GENERAL']
    category: str = Field(default='', max_length=128)
    tags: list[str] = Field(default_factory=list, max_length=12)
    readTimeMinutes: int = Field(ge=1, le=120)
    isPublished: bool = Field(default=False, strict=True)

    @field_validator('tag', mode='before')
    @classmethod
    def normalize_tag(cls, value):
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator('tags', mode='before')
    @classmethod
    def normalize_tags(cls, value):
        if isinstance(value, str):
            value = value.split(',')
        if not isinstance(value, list):
            return value
        result, seen = [], set()
        for item in value:
            if not isinstance(item, str) or len(item) > 128:
                raise ValueError('Tags must be text of at most 128 characters')
            item = item.strip()
            if item and item.casefold() not in seen:
                result.append(item)
                seen.add(item.casefold())
        return result


def article_item(row, content=False, draft=False):
    item = {key: row[key] for key in ('id', 'title', 'excerpt', 'tag', 'category', 'views', 'helpful', 'readTimeMinutes')}
    item['tags'] = [tag for tag in row['tags'] if isinstance(tag, str) and tag.strip()] if isinstance(row['tags'], list) else []
    item['updated'] = f"{row['updatedAt'].month}/{row['updatedAt'].day}/{row['updatedAt'].year}"
    if content:
        item['content'] = row['content']
    if draft:
        item['isPublished'] = row['isPublished']
    return item


@router.get('/knowledge-base')
def articles(search: str = '', tag: str = '', category: str = '', includeDraft: str = '', includeContent: str = '',
             limit: int = Query(100, ge=1, le=200), user=Depends(staff), db=Depends(get_db)):
    privileged = user.role in ('admin', 'hr')
    records = rows(db, 'KnowledgeBaseArticle')
    matches = [row for row in records if (row['isPublished'] or privileged and includeDraft == '1')
        and (not tag or row['tag'] == tag.strip().upper()) and (not category or row['category'] == category.strip())
        and search.strip().casefold() in (row['title'] + ' ' + row['excerpt']).casefold()]
    matches.sort(key=lambda row: (row['views'], row['updatedAt']), reverse=True)
    return {'articles': [article_item(row, privileged and includeContent == '1', privileged) for row in matches[:limit]]}


@router.post('/knowledge-base', status_code=201)
def add_article(body: ArticleInput, user=Depends(admin), db=Depends(get_db)):
    row = insert(db, 'KnowledgeBaseArticle', {**body.model_dump(), 'publishedAt': now() if body.isPublished else None, 'views': 0, 'helpful': 0})
    return {'article': article_item(row, True, True)}


@router.patch('/knowledge-base/{id}')
def edit_article(id: str, body: ArticleInput, user=Depends(admin), db=Depends(get_db)):
    existing = find(db, 'KnowledgeBaseArticle', id, lock=True)
    row = update(db, 'KnowledgeBaseArticle', id, {**body.model_dump(), 'publishedAt': (existing['publishedAt'] or now()) if body.isPublished else None})
    return {'article': article_item(row, True, True)}


@router.delete('/knowledge-base/{id}', status_code=204)
def delete_article(id: str, user=Depends(admin), db=Depends(get_db)):
    return delete_record(db, 'KnowledgeBaseArticle', id)
