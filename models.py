from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Ingredient(db.Model):
    __tablename__ = 'ingredients'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50))  # Meat, Vegetable, etc.
    mode = db.Column(db.String(20), default='precision')  # precision(정밀), simple(약식)
    standard_unit = db.Column(db.String(20), default='g') # g, ml, count
    
    # Calculated fields (denormalized for performance, or calculated on fly)
    # We will calculate these dynamically for now or update them on transaction
    
    purchases = db.relationship('Purchase', backref='ingredient', lazy=True)
    usages = db.relationship('Usage', backref='ingredient', lazy=True)

class ShoppingEvent(db.Model):
    __tablename__ = 'shopping_events'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    place = db.Column(db.String(100))
    total_cost = db.Column(db.Float, default=0.0)
    total_waste = db.Column(db.Float, default=0.0)
    
    purchases = db.relationship('Purchase', backref='shopping_event', lazy=True)

class Purchase(db.Model):
    __tablename__ = 'purchases'
    id = db.Column(db.Integer, primary_key=True)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredients.id'), nullable=False)
    purchase_date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    quantity = db.Column(db.Float, nullable=False) # Initial quantity
    remaining_quantity = db.Column(db.Float, nullable=False) # For FIFO tracking
    cost_per_unit = db.Column(db.Float, nullable=False) # Calculated: Total Price / Quantity
    expiry_date = db.Column(db.Date)
    
    # Link to Shopping Event
    shopping_event_id = db.Column(db.Integer, db.ForeignKey('shopping_events.id'))
    
    # Status: 'active', 'used', 'discarded'
    status = db.Column(db.String(20), default='active') 
    
    # Discard/Waste tracking
    discarded_quantity = db.Column(db.Float, default=0.0)
    discarded_cost = db.Column(db.Float, default=0.0)

class Usage(db.Model):
    __tablename__ = 'usages'
    id = db.Column(db.Integer, primary_key=True)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredients.id'), nullable=False)
    usage_date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    meal_type = db.Column(db.String(50)) # Breakfast, Lunch, Dinner, Snack, Adjustment(Daily Close)
    
    input_unit = db.Column(db.String(50)) # e.g., "1 Tbsp"
    actual_usage = db.Column(db.Float, nullable=False) # Converted to standard unit (e.g., 15g)
    
    cost = db.Column(db.Float, nullable=False) # Calculated via FIFO

class UnitMatrix(db.Model):
    __tablename__ = 'unit_matrix'
    id = db.Column(db.Integer, primary_key=True)
    unit_name = db.Column(db.String(50), unique=True) # e.g., "Tbsp", "Cup"
    ratio_to_standard = db.Column(db.Float, nullable=False) # Multiplier to get g/ml
    guide_image_url = db.Column(db.String(200))

