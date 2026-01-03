from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, Ingredient, Purchase, Usage, UnitMatrix, ShoppingEvent, User
from datetime import datetime, date
import os

app = Flask(__name__)

# Database Configuration
# Use 'DATABASE_URL' from environment or fallback to local SQLite
database_url = os.environ.get('DATABASE_URL', 'sqlite:///food_manager_v2.db')

# Fix for Heroku/Render 'postgres://' (SQLAlchemy requires 'postgresql://')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'antigravity_secret'

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Auth Routes ---
@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        if user:
            flash('Email already exists')
            return redirect(url_for('signup'))
            
        new_user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(new_user)
        db.session.commit()
        
        login_user(new_user)
        return redirect(url_for('dashboard'))
        
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash('Please check your login details and try again.')
            return redirect(url_for('login'))
            
        login_user(user)
        return redirect(url_for('dashboard'))
        
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- Business Logic Helpers ---

def calculate_fifo_cost(ingredient_id, needed_qty):
    """
    Calculate cost for `needed_qty` using FIFO from Purchases.
    Updates `remaining_quantity` in Purchase records.
    Returns calculated cost.
    """
    ingredient = Ingredient.query.get(ingredient_id)
    if not ingredient:
        return 0.0

    # Sort purchases by date (and expiry if available) to ensure FIFO
    # We use purchase_date asc. If same day, maybe expiry?
    purchases = Purchase.query.filter(
        Purchase.ingredient_id == ingredient_id, 
        Purchase.remaining_quantity > 0
    ).order_by(Purchase.purchase_date.asc(), Purchase.expiry_date.asc()).all()

    total_cost = 0.0
    qty_to_fill = needed_qty

    for p in purchases:
        if qty_to_fill <= 0:
            break
        
        take = min(p.remaining_quantity, qty_to_fill)
        cost_chunk = take * p.cost_per_unit
        
        # update purchase record
        p.remaining_quantity -= take
        
        total_cost += cost_chunk
        qty_to_fill -= take
        
    # Commit changes to purchases (inventory reduction)
    db.session.commit()
    return total_cost

def get_total_asset_value():
    """Calculate total value of current inventory (Cost of Goods on Hand)"""
    purchases = Purchase.query.filter(Purchase.remaining_quantity > 0).all()
    total = sum(p.remaining_quantity * p.cost_per_unit for p in purchases)
    return total

def get_expiring_items(days=3):
    today = date.today()
    items = []
    purchases = Purchase.query.filter(Purchase.remaining_quantity > 0).all()
    for p in purchases:
        if p.expiry_date:
            delta = (p.expiry_date - today).days
            if 0 <= delta <= days:
                loss_val = p.remaining_quantity * p.cost_per_unit
                items.append({
                    'id': p.id,
                    'name': p.ingredient.name,
                    'days_left': delta,
                    'potential_loss': loss_val,
                    'qty': p.remaining_quantity,
                    'unit': p.ingredient.standard_unit
                })
    return items

# --- Routes ---

@app.route('/links')
def links():
    return render_template('links.html')

@app.route('/')
@login_required
def dashboard():
    total_asset = get_total_asset_value()
    expiring_list = get_expiring_items()
    
    # Simple daily report logic
    today_usages = Usage.query.filter(Usage.usage_date == date.today()).all()
    daily_cost = sum(u.cost for u in today_usages)
    
    today = date.today()
    start_month = date(today.year, today.month, 1)
    if today.month == 12:
        end_month = date(today.year + 1, 1, 1)
    else:
        end_month = date(today.year, today.month + 1, 1)
        
    # Monthly Shopping Total
    monthly_shopping = db.session.query(db.func.sum(ShoppingEvent.total_cost)).filter(
        ShoppingEvent.date >= start_month,
        ShoppingEvent.date < end_month
    ).scalar() or 0
    
    # Monthly Waste Total
    monthly_waste = db.session.query(db.func.sum(ShoppingEvent.total_waste)).filter(
        ShoppingEvent.date >= start_month,
        ShoppingEvent.date < end_month
    ).scalar() or 0

    # Monthly Usage (Consumption) Total
    monthly_usage = db.session.query(db.func.sum(Usage.cost)).filter(
        Usage.usage_date >= start_month,
        Usage.usage_date < end_month
    ).scalar() or 0
    
    current_month_str = f"{today.month}월"

    # Cumulative Waste (All Time)
    cumulative_waste = db.session.query(db.func.sum(ShoppingEvent.total_waste)).scalar() or 0

    return render_template('dashboard.html', 
                           total_asset=total_asset, 
                           monthly_shopping=monthly_shopping,
                           monthly_waste=monthly_waste,
                           monthly_usage=monthly_usage,
                           daily_cost=daily_cost,
                           cumulative_waste=cumulative_waste,
                           current_month_str=current_month_str,
                           expiring=expiring_list)

@app.route('/inventory')
@login_required
def inventory():
    # Show detailed active purchases (Inventory Batches)
    purchases = Purchase.query.filter(Purchase.remaining_quantity > 0).order_by(Purchase.expiry_date.asc()).all()
    return render_template('inventory.html', purchases=purchases)

@app.route('/add_ingredient', methods=['POST'])
def add_ingredient():
    # Keep this for manual creation if needed, or redirect to inventory
    # But usually handled in purchase now.
    pass 

@app.route('/purchase', methods=['GET', 'POST'])
@login_required
def purchase():
    if request.method == 'POST':
        # Batch Purchase Logic
        # Expecting JSON data now for multi-row
        if request.is_json:
            data = request.get_json()
            
            p_date_str = data.get('date')
            p_place = data.get('place', '')
            items = data.get('items', [])
            
            p_date = datetime.strptime(p_date_str, '%Y-%m-%d').date()
            
            # Create Event
            event = ShoppingEvent(date=p_date, place=p_place, total_cost=0, total_waste=0)
            db.session.add(event)
            db.session.commit() # Commit to get ID
            
            total_trip_cost = 0
            
            # Calculate Discount Ratio
            raw_total = sum(float(item['price']) for item in items)
            total_pay_input = data.get('total_pay')
            
            discount_ratio = 1.0
            if total_pay_input is not None and raw_total > 0:
                 # If user entered a specific total payment, logic:
                 # Ratio = Total Pay / Raw Total
                 discount_ratio = float(total_pay_input) / raw_total
            
            for item in items:
                name = item['name']
                qty = float(item['qty'])
                unit = item['unit']
                price = float(item['price']) # Total price for this item
                expiry_str = item.get('expiry')
                
                # Find/Create Ingredient
                ing = Ingredient.query.filter_by(name=name, user_id=current_user.id).first()
                if not ing:
                    ing = Ingredient(name=name, category='일반', mode='precision', standard_unit=unit, user_id=current_user.id)
                    db.session.add(ing)
                    db.session.commit()
                
                # Apply Discount Ratio to individual item price
                final_item_price = price * discount_ratio
                
                cost_unit = final_item_price / qty if qty > 0 else 0
                total_trip_cost += final_item_price
                
                e_date = datetime.strptime(expiry_str, '%Y-%m-%d').date() if expiry_str else None
                
                new_p = Purchase(
                    ingredient_id=ing.id,
                    purchase_date=p_date,
                    quantity=qty,
                    remaining_quantity=qty,
                    cost_per_unit=cost_unit,
                    expiry_date=e_date,
                    shopping_event_id=event.id,
                    status='active'
                )
                db.session.add(new_p)
                
            event.total_cost = total_trip_cost
            db.session.commit()
            return jsonify({'success': True})
            
    # For datalist suggestion
    # Pre-fill date if passed
    target_date = request.args.get('date', date.today().strftime('%Y-%m-%d'))
    
    ingredients = Ingredient.query.all()
    return render_template('purchase.html', ingredients=ingredients, target_date=target_date)

@app.route('/api/discard/<int:purchase_id>', methods=['POST'])
def discard_item(purchase_id):
    p = Purchase.query.get(purchase_id)
    if not p:
        return jsonify({'error': 'Not found'}), 404
        
    data = request.get_json()
    amount = float(data.get('amount', p.remaining_quantity)) # Default discard all remaining
    
    if amount > p.remaining_quantity:
        return jsonify({'error': 'Exceeds remaining'}), 400
        
    # Calculate waste cost
    waste_cost = amount * p.cost_per_unit
    
    p.remaining_quantity -= amount
    p.discarded_quantity += amount
    p.discarded_cost += waste_cost
    
    if p.remaining_quantity == 0:
        p.status = 'discarded'
        
    # Update Event Waste Total
    if p.shopping_event_id:
        event = ShoppingEvent.query.get(p.shopping_event_id)
        # Recalculate full waste for event to be safe or just add
        event.total_waste += waste_cost
        
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/shopping_events')
def api_shopping_events():
    # Return events for calendar
    events = ShoppingEvent.query.all()
    # Or filter by month if needed
    data = []
    for e in events:
        data.append({
            'id': e.id,
            'date': e.date.strftime('%Y-%m-%d'),
            'total_cost': e.total_cost,
            'total_waste': e.total_waste
        })
    return jsonify(data)

@app.route('/api/shopping_event_detail/<int:event_id>')
def api_shopping_event_detail(event_id):
    event = ShoppingEvent.query.get(event_id)
    if not event: return jsonify({})
    
    items = []
    for p in event.purchases:
        items.append({
            'id': p.id,
            'name': p.ingredient.name,
            'qty': p.quantity,
            'remaining': p.remaining_quantity,
            'price': p.quantity * p.cost_per_unit,
            'waste_cost': p.discarded_cost,
            'status': p.status
        })
        
    return jsonify({
        'id': event.id,
        'date': event.date.strftime('%Y-%m-%d'),
        'total_cost': event.total_cost,
        'total_waste': event.total_waste,
        'items': items
    })


@app.route('/delete_usage/<int:usage_id>', methods=['POST'])
def delete_usage(usage_id):
    usage = Usage.query.get(usage_id)
    if usage:
        # Restore stock (Simplification: Add to any available batch or most recent)
        # Ideally we should know which batch it came from, but we didn't track it explicitly in Many-to-Many
        # So we just find the most relevant Purchase to refund.
        # We try to find a purchase with same ingredient.
        purchase = Purchase.query.filter_by(ingredient_id=usage.ingredient_id).order_by(Purchase.purchase_date.desc()).first()
        if purchase:
            purchase.remaining_quantity += usage.actual_usage
        
        db.session.delete(usage)
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False}), 400

@app.route('/cook', methods=['GET', 'POST'])
@login_required
def cook():
    if request.method == 'POST':
        # Batch Usage Logic
        if request.is_json:
            data = request.get_json()
            
            u_date_str = data.get('usage_date')
            meal_type = data.get('meal_type', 'Snack') # Now free-text input
            items = data.get('items', [])
            
            u_date = datetime.strptime(u_date_str, '%Y-%m-%d').date()
            
            for item in items:
                ing_id = int(item['ingredient_id'])
                input_amount = float(item.get('amount', 0))
                unit_name = item.get('unit_name', 'std')
                
                final_qty = input_amount
                
                # Check Unit
                matrix = UnitMatrix.query.filter_by(unit_name=unit_name).first()
                if matrix:
                    final_qty = input_amount * matrix.ratio_to_standard
                    
                cost = calculate_fifo_cost(ing_id, final_qty)
                
                new_usage = Usage(
                    ingredient_id=ing_id,
                    usage_date=u_date,
                    meal_type=meal_type,
                    input_unit=f"{input_amount} {unit_name}",
                    actual_usage=final_qty,
                    cost=cost
                )
                db.session.add(new_usage)
            
            db.session.commit()
            return jsonify({'success': True})

        # Fallback for old form (should not be used by new UI but good to handle or reject)
        # Simplified: just error or redirect if not json, as we replaced the frontend
        return redirect(url_for('dashboard'))

    # Pre-fill date if passed
    target_date = request.args.get('date', date.today().strftime('%Y-%m-%d'))
    
    ingredients = Ingredient.query.all()
    
    # Calculate estimated cost for frontend display (next available purchase)
    for ing in ingredients:
        next_batch = Purchase.query.filter(
            Purchase.ingredient_id == ing.id, 
            Purchase.remaining_quantity > 0
        ).order_by(Purchase.purchase_date.asc(), Purchase.expiry_date.asc()).first()
        
        ing.estimated_cost = next_batch.cost_per_unit if next_batch else 0

    units = UnitMatrix.query.all()
    return render_template('kitchen.html', ingredients=ingredients, units=units, target_date=target_date)

@app.context_processor
def inject_now():
    def get_date_now(today_only=False):
        if today_only:
            return date.today()
        return date.today().strftime('%Y-%m-%d')
    return {'date_now': get_date_now}

@app.route('/api/monthly_stats')
def monthly_stats():
    year = int(request.args.get('year'))
    month = int(request.args.get('month'))
    
    # Calculate Date Range
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)
        
    # 1. Usage Costs (Date of Consumption)
    usages = Usage.query.filter(
        Usage.usage_date >= start_date,
        Usage.usage_date < end_date
    ).all()
    
    # 2. Shopping Waste (Date of Shopping Event)
    # We attribute waste cost to the Shopping Event date as per plan
    events = ShoppingEvent.query.filter(
        ShoppingEvent.date >= start_date,
        ShoppingEvent.date < end_date
    ).all()
    
    data = {}
    
    # Sum Usage
    for u in usages:
        day_str = u.usage_date.strftime('%Y-%m-%d')
        if day_str not in data:
            data[day_str] = {'usage': 0, 'waste': 0, 'total': 0}
        data[day_str]['usage'] += u.cost
        data[day_str]['total'] += u.cost
        
    # Sum Waste
    for e in events:
        day_str = e.date.strftime('%Y-%m-%d')
        if e.total_waste > 0:
            if day_str not in data:
                data[day_str] = {'usage': 0, 'waste': 0, 'total': 0}
            data[day_str]['waste'] += e.total_waste
            data[day_str]['total'] += e.total_waste
        
    return jsonify(data)

@app.route('/api/update_purchase_status/<int:purchase_id>', methods=['POST'])
def update_purchase_status(purchase_id):
    p = Purchase.query.get(purchase_id)
    if not p: return jsonify({'success': False}), 404
    
    data = request.get_json()
    new_status = data.get('status') # 'active', 'discarded'
    
    if new_status == 'discarded' and p.status != 'discarded':
        # Full discard
        waste_cost = p.remaining_quantity * p.cost_per_unit
        p.discarded_quantity += p.remaining_quantity
        p.remaining_quantity = 0
        p.discarded_cost += waste_cost
        p.status = 'discarded'
        
        # Update Event
        if p.shopping_event_id:
            evt = ShoppingEvent.query.get(p.shopping_event_id)
            evt.total_waste += waste_cost
            
    # Note: Reverting discard is complex (how much to restore?), separate task.
    # For now support one-way or simple toggle if needed (reset if accidental?)
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/daily_detail/<date_str>')
def daily_detail(date_str):
    target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    usages = Usage.query.filter(Usage.usage_date == target_date).all()
    
    # Group by meal type
    grouped = {}
    for u in usages:
        if u.meal_type not in grouped:
            grouped[u.meal_type] = {'total': 0, 'items': []}
        
        grouped[u.meal_type]['total'] += u.cost
        grouped[u.meal_type]['items'].append({
            'id': u.id,
            'name': u.ingredient.name,
            'amount': u.input_unit,
            'cost': u.cost
        })
        
@app.route('/api/delete_usage/<int:usage_id>', methods=['POST'])
def api_delete_usage(usage_id):
    usage = Usage.query.get_or_404(usage_id)
    ingredient_id = usage.ingredient_id
    qty_to_restore = usage.actual_usage
    
    # Inventory Restoration Logic (Reverse FIFO approximation)
    # We look for purchases that are not full (remaining < initial)
    # and fill them up, starting from oldest (since that's what we likely consumed from).
    purchases = Purchase.query.filter(
        Purchase.ingredient_id == ingredient_id,
        Purchase.remaining_quantity < Purchase.quantity
    ).order_by(Purchase.purchase_date.asc(), Purchase.expiry_date.asc()).all()
    
    remaining_to_restore = qty_to_restore
    
    for p in purchases:
        if remaining_to_restore <= 0:
            break
            
        space = p.quantity - p.remaining_quantity
        restore_amount = min(space, remaining_to_restore)
        
        p.remaining_quantity += restore_amount
        remaining_to_restore -= restore_amount
        
    # If still remaining (e.g. original purchase deleted?), add to the most recent active purchase
    # or just the most recent purchase available.
    if remaining_to_restore > 0:
        last_purchase = Purchase.query.filter_by(ingredient_id=ingredient_id).order_by(Purchase.purchase_date.desc()).first()
        if last_purchase:
            last_purchase.remaining_quantity += remaining_to_restore

    db.session.delete(usage)
    db.session.commit()
    return jsonify({'success': True})


with app.app_context():
    db.create_all()
    # Seed Basic Units if empty
    if not UnitMatrix.query.first():
        db.session.add(UnitMatrix(unit_name='큰술', ratio_to_standard=15, guide_image_url='')) # 15ml/g
        db.session.add(UnitMatrix(unit_name='컵', ratio_to_standard=200, guide_image_url='')) # 200ml/g
        db.session.add(UnitMatrix(unit_name='작은술', ratio_to_standard=5, guide_image_url='')) # 5ml/g
        # Seed Ingredients for demo
        if not Ingredient.query.first():
             db.session.add(Ingredient(name='우유', category='유제품', standard_unit='ml'))
             db.session.add(Ingredient(name='계란', category='유제품', standard_unit='count'))
             db.session.add(Ingredient(name='삼겹살', category='육류', standard_unit='g'))
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
