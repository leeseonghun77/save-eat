from app import app, db, UnitMatrix, Usage

def run_migration():
    with app.app_context():
        print("Migrating UnitMatrix...")
        # 1. Update UnitMatrix
        mappings = {
            'Tbsp': '큰술',
            'Cup': '컵',
            'Tsp': '작은술'
        }
        
        for old_name, new_name in mappings.items():
            unit = UnitMatrix.query.filter_by(unit_name=old_name).first()
            if unit:
                unit.unit_name = new_name
                print(f"Updated UnitMatrix: {old_name} -> {new_name}")
        
        db.session.commit()
        
        # 2. Update Usages (input_unit text)
        print("Migrating Usage records...")
        usages = Usage.query.all()
        count = 0
        for u in usages:
            changed = False
            for old_name, new_name in mappings.items():
                if old_name in u.input_unit:
                    u.input_unit = u.input_unit.replace(old_name, new_name)
                    changed = True
            
            if changed:
                count += 1
                
        db.session.commit()
        print(f"Updated {count} usage records.")
        print("Migration Complete.")

if __name__ == "__main__":
    run_migration()
