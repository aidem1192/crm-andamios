from app.database import SessionLocal, Usuario

db = SessionLocal()
usuarios = db.query(Usuario).order_by(Usuario.id).all()
print("=== USUARIOS EN PRODUCCION ===")
for u in usuarios:
    print(f"id={u.id} username={u.username!r} nombre={u.nombre!r} rol={u.rol} activo={u.activo}")
print("=== FIN ===")
db.close()
