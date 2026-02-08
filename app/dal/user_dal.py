from sqlalchemy.orm import Session
from app import models, schemas
from app.utils.identifiers import generate_user_id


def get_user(db: Session, user_id: str):
    return db.query(models.User).filter(models.User.user_id == user_id).first()


def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()


def get_users(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.User).offset(skip).limit(limit).all()


def create_user(db: Session, user: schemas.UserCreate):
    hashed_password = user.password + "notreallyhashed"  # TODO: Hash the password
    user_id = generate_user_id(db, user.first_name, user.last_name)
    db_user = models.User(
        user_id=user_id,
        email=user.email,
        hashed_password=hashed_password,
        login=user.login,
        first_name=user.first_name,
        last_name=user.last_name,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user
