import os
from zoneinfo import ZoneInfo

from flask import Flask, render_template, request, jsonify
from flask_restful import Api
from flask_socketio import SocketIO

from app import db
from app.api_config import APIConfig
from app.api_resources import (CancelItemAPI, CancelOrderAPI, CreateOrderAPI,
                               FinishItemAPI, FinishOrderAPI,
                               GetOrderInRangeAPI, GetSingleTableAPI,
                               GetUserAPI, RefundOrderAPI, UserNameAPI, InsertUserActionsAPI,OrderActionsAPI)
from app.cache import cache
from app.services import OrderService, TableService, GetOrder
from app.utils import Utils
from flask_cors import CORS
import requests
import json
from app.inventory_action import *
from flask_caching import Cache
from app.telegram_bot import *
import pandas as pd

def create_app(test_config=None):
    print("called")
    # Configure a new Flask app
    app = Flask(__name__, instance_relative_config=True, static_folder="static")

    cache = Cache(config={'CACHE_TYPE': 'redis', 'CACHE_REDIS_URL': 'redis://localhost:6379/0'})
    cache.init_app(app)

    CORS(app)

    if test_config is None:
        app.config.from_pyfile("config.py", silent=True)
    else:
        app.config.from_mapping(test_config)

    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", Utils.DEFAULT_SECRET_KEY)
    app.config["PINCODE"] = os.environ.get("PINCODE", Utils.DEFAULT_PINCODE)
    app.config["TIMEZONE"] = ZoneInfo(
        os.environ.get("TIMEZONE", Utils.DEFAULT_TIMEZONE))
    # print(app.config["TIMEZONE"])
    # Database configuration
    app.config["DATABASE"] = "postgres://username:password@localhost:5432/kds"
    # print(app.config["DATABASE"])
    # Maximum items for the dine-in
    app.config["MAX_TABLE"] = int(os.environ.get(
        "MAX_TABLE", Utils.DEFAULT_MAX_TABLE))
    app.config["MAX_TABLE_PER_ROW"] = int(os.environ.get(
        "MAX_TABLE_PER_ROW", Utils.DEFAULT_MAX_TABLE_PER_ROW))
    print(app.config["MAX_TABLE_PER_ROW"])
    # Maximum items recommended
    app.config["MAX_RECOMMEND_ITEMS"] = int(os.environ.get(
        "MAX_RECOMMEND_ITEMS", Utils.DEFAULT_MAX_BESTSELLER_RECOMMEND))

    # Configuration for Redis cache
    app.config["CACHE_TYPE"] = os.environ.get("CACHE_TYPE", "simple")
    app.config["CACHE_REDIS_URL"] = os.environ.get("CACHE_REDIS_URL", "redis://localhost:6379/0")

    # Ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass
    
    # Configure database
    db.init_app(app=app)

    # Configure socketio
    socket_io = SocketIO(app=app)

    # Configure caching
    # Configure caching
    cache.init_app(app=app, config={
        "CACHE_TYPE": app.config.get("CACHE_TYPE"),  # Provide a default value
        "CACHE_REDIS_URL": app.config.get("CACHE_REDIS_URL"),  # Provide a default value
    })


    # Configure Flask-RESTful
    api = Api(app=app, prefix=APIConfig.PREFIX)

    # User API
    api.add_resource(GetUserAPI, APIConfig.get_resource_endpoint(
        "GET_USER_API"), endpoint="user_get")
    api.add_resource(UserNameAPI, APIConfig.get_resource_endpoint(
        "GET_USER_NAME_API"), endpoint="user_name")

    # Orders API
    api.add_resource(CreateOrderAPI, APIConfig.get_resource_endpoint(
        "CREATE_ORDER_API"),
        endpoint="create",
        resource_class_kwargs={"socket_io": socket_io})
    api.add_resource(FinishOrderAPI, APIConfig.get_resource_endpoint(
        "FINISH_ORDER_API"), endpoint="order_finish")
    api.add_resource(CancelOrderAPI, APIConfig.get_resource_endpoint(
        "CANCEL_ORDER_API"), endpoint="order_cancel")
    api.add_resource(RefundOrderAPI, APIConfig.get_resource_endpoint(
        "REFUND_ORDER_API"), endpoint="order_refund")
    api.add_resource(FinishItemAPI, APIConfig.get_resource_endpoint(
        "FINISH_ITEM_API"), endpoint="item_finish")
    api.add_resource(OrderActionsAPI,APIConfig.get_resource_endpoint(
        "GET_USER_ACTIONS"), endpoint="order_actions")
    api.add_resource(CancelItemAPI, APIConfig.get_resource_endpoint(
        "CANCEL_ITEM_API"), endpoint="item_cancel")
    api.add_resource(
        GetSingleTableAPI, APIConfig.get_resource_endpoint(
            "GET_SINGLE_TABLE_API"),
        endpoint="get_single_order")
    api.add_resource(GetOrderInRangeAPI, APIConfig.get_resource_endpoint(
        "GET_ORDER_IN_RANGE_API"), endpoint="get_order_in_range")
    api.add_resource(InsertUserActionsAPI, APIConfig.get_resource_endpoint(
    "CREATE_USER_ACTIONS"), endpoint="create_user_actions")

    # Home (KDS) route
    @app.route("/", endpoint="home")
    def home():
        print("---------home---------")
        list_unfinished_dine_in_orders = OrderService.get_table_in_progress_orders_service(
            max_table=app.config["MAX_TABLE"])
        print("List unfinished dine in order : ",list_unfinished_dine_in_orders)
        list_unfinished_take_away_orders = OrderService.get_take_away_orders_service()

        # Count total orders (for badging)
        total_dinein_orders = sum(len(i)
                                  for i in
                                  list_unfinished_dine_in_orders.values())
        total_takeaway_orders = len(list_unfinished_take_away_orders)

        return render_template(
            "html/kds/kds-dashboard.html",
            dine_in_tables=list_unfinished_dine_in_orders,
            total_dinein_orders=total_dinein_orders,
            total_takeaway_orders=total_takeaway_orders,
            total_tables=len(list_unfinished_dine_in_orders),
            max_table=app.config["MAX_TABLE"],
            max_table_per_row=app.config["MAX_TABLE_PER_ROW"],
            padding=app.config["MAX_TABLE_PER_ROW"] - app.config["MAX_TABLE"] %
            app.config["MAX_TABLE_PER_ROW"],
            take_away_orders=list_unfinished_take_away_orders,)

    # Order History route
    @app.route("/history/orders", endpoint="order_history")
    def order_history():
        return render_template(
            "html/history/order/dashboard.html",
            all_table=TableService.get_all_record_distinct_tables_service())
    

    # User History roure
    @app.route("/history/users", endpoint="user_history")
    def user_history():
        return render_template("html/history/user/dashboard.html")

    # Sales stats route
    @app.route("/weekly-stats", endpoint="weekly_stats")
    def weekly_stats():
        return render_template("html/stats/dashboard.html")

    # Parking Bottle route
    @app.route("/parking", endpoint="parking_bottle")
    def parking_bottle():
        return render_template("html/parking/dashboard.html")

    # Render javascript files including routes

    @app.route("/kdsactionjs")
    def kdsactionjs():
        return render_template("js/kds-action.js")

    @app.route("/historyactionjs")
    def historyactionjs():
        return render_template("js/history-action.js")

    @app.route("/userhistoryjs")
    def userhistoryjs():
        return render_template("js/user-history.js")

    @app.route("/parkingactionjs")
    def parkingactionjs():
        return render_template("js/parking-action.js")

    @app.route("/weekstatactionjs")
    def weekstatactionjs():
        return render_template("js/week-stat-action.js")
    

    # ---------------- INVENTORY ROUTES & HELPER FUNCTIONS ----------------------- #
    
    @app.route('/inventory')
    def inventory():
        inventory_data = read_csv("inventory.csv")
        return render_template('/html/inventory.html', inventory=inventory_data)
    
    @app.route('/datas')
    def data():
        return render_template('data.html')
    
    @app.route('/check')
    def check():
        return render_template('check.html')
    
    @app.route('/get_missing_ingredients', methods=['GET'])
    def get_missing_ingredients():
        try:
            menu = read_csv('menu.csv')
            inventory = read_csv('inventory.csv')
            mappings = read_csv('mappings.csv')

            missing_ingredients = {}
            for item in menu:
                item_name = item['item_name']
                quantity = int(item['quantity'])
                if not check_inventory_availability(item_name, quantity, inventory, mappings):
                    missing = calculate_missing_ingredients(item_name, quantity, inventory, mappings)
                    if missing:
                        missing_ingredients[item_name] = missing

            return jsonify(missing_ingredients), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    @app.route('/get_menu_with_availability', methods=['GET'])
    def get_menu_with_availability():
        try:
            menu = read_csv('menu.csv')
            inventory = read_csv('inventory.csv')
            mappings = read_csv('mappings.csv')

            menu_with_availability = []
            for item in menu:
                item_name = item['item_name']
                quantity = int(item['quantity'])
                low_count = int(item['low_count'])
                available = check_inventory_availability(item_name, quantity, inventory, mappings)
                menu_with_availability.append({
                    'item_name': item_name,
                    'quantity': quantity,
                    'available': available,
                    'low_count': low_count
                })

            return jsonify(menu_with_availability), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        


    # --------------- TAKEAWAY AUTO INVENTORY UPDATE ---------------- # 

    @app.route('/update_inventory/<int:order_id>', methods=['POST'])
    def update_inventory(order_id: int):
        try:
            # Fetch order details from external API or database
            order_details = GetOrder.get_order_details(order_id)
            
            # Check if the retrieved data is a list of items
            if not isinstance(order_details, list):
                return jsonify({"error": "Invalid input. Expected a list of items with 'item_name' and 'quantity'."}), 400

            # Read existing data from CSV files
            inventory = read_csv('inventory.csv')
            mappings = read_csv('mappings.csv')
            menu = read_csv('menu.csv')

            data = []

            # Process each item in the order
            for item in order_details:
                item_name = item.get('item_name')
                quantity = item.get('quantity')

                data.append(item_name)
                
                # Validate item format
                if not item_name or quantity is None:
                    return jsonify({"error": "Invalid item format. Each item must have 'item_name' and 'quantity'."}), 400

                # Update inventory and mappings
                error_message, status_code = update_ingredient_inventory(item_name, quantity, inventory, mappings)
                if error_message:
                    return jsonify({"error": error_message}), status_code

                # Update menu item quantities
                for menu_item in menu:
                    if menu_item['item_name'] == item_name:
                        menu_item['quantity'] = str(int(menu_item['quantity']) - quantity)
                        break
                else:
                    return jsonify({"error": f"Item '{item_name}' not found in menu"}), 404
                
            message = f"Takeaway Order for order id: {order_id} is completed. Order Details are: {[i for i in data]}\n"
                
            send_telegram_message(message)

            # Write updated data back to CSV files
            write_csv('inventory.csv', inventory)
            write_csv('menu.csv', menu)

            return jsonify({"message": "Inventory and menu updated successfully."}), 200

        except Exception as e:
            return jsonify({"error": str(e)}), 500


    # --------------- DINE IN AUTO INVENTORY UPDATE ---------------- #

    @app.route('/auto_update_inventory', methods=['POST'])
    def auto_update_inventory():
        try:
            data = request.get_json()
            table_id = data.get('table_id')

            if not table_id:
                return jsonify({'error': 'Missing table_id in request'}), 400

            url = 'http://localhost:5000/api/v1/order/get'
            headers = {'Content-Type': 'application/json'}
            response = requests.post(url, data=json.dumps(data), headers=headers)

            if response.status_code == 200:
                order_data = response.json()
                order_list = order_data.get('order_list')

                if not order_list:
                    return jsonify({'error': 'No order_list found in response'}), 404
                
                mydict = order_list[0]
                extracted_data = [
                        {'item_name': item['name'], 'quantity': item['quantity']}
                        for item in mydict[0]['order_items']
                    ]
                
                if not isinstance(extracted_data, list):
                    return jsonify({"error": "Invalid input. Expected a list of items with 'item_name' and 'quantity'."}), 400

                inventory = read_csv('inventory.csv')
                mappings = read_csv('mappings.csv')
                menu = read_csv('menu.csv')

                for item in extracted_data:
                    item_name = item.get('item_name')
                    quantity = item.get('quantity')

                    if not item_name or quantity is None:
                        return jsonify({"error": "Invalid item format. Each item must have 'item_name' and 'quantity'."}), 400

                    error_message, status_code = update_ingredient_inventory(item_name, quantity, inventory, mappings)

                    if error_message:
                        return jsonify({"error": error_message}), status_code

                    # Update menu quantities
                    for menu_item in menu:
                        if menu_item['item_name'] == item_name:
                            menu_item['quantity'] = str(int(menu_item['quantity']) - quantity)
                            break

                write_csv('inventory.csv', inventory)
                write_csv('menu.csv', menu)
                # Prepare the message to be sent to Telegram
                message = f"Order for table {table_id} completed. Order details are: {[ i for i in extracted_data]}\n"
                
                send_telegram_message(message)

                return jsonify({"message": "Success"}), 200

            else:
                return jsonify({'error': 'Failed to fetch order details'}), response.status_code

        except Exception as e:
            return jsonify({'error': str(e)}), 500
        

    # ------------------- ORDER HANDLING ------------------- #

    @app.route('/order/<int:order_id>', methods=['GET'])
    def get_order_details(order_id: int):
        """API endpoint to get details of a specific order by ID"""
        try:
            order_details = GetOrder.get_order_details(order_id)
            return jsonify(order_details), 200
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        
    @app.route('/get_order_list', methods=['POST'])
    def get_order_list():
        
        try:
            
            # Get JSON data from the request
            data = request.get_json()


            # Validate if 'table_id' is in the request data
            table_id = data.get('table_id')


            if not table_id:
                return jsonify({'error': 'Missing table_id in request'}), 400

            # Define the URL of the Flask server where the API endpoint is hosted
            url = 'http://localhost:5000/api/v1/order/get'

            # Headers (optional)
            headers = {'Content-Type': 'application/json'}

            # Sending POST request to the API
            response = requests.post(url, data=json.dumps(data), headers=headers)



            # Check if request was successful (HTTP status code 200)
            if response.status_code == 200:
                data = response.json()
                order_list = data.get('order_list')



                if order_list:
                    # Assuming order_list is a list and extracting first item
                    mydict = order_list[0]

                    # Extracting item_name and quantity from order_items
                    extracted_data = extracted_data = [
                        {'item_name': item['name'], 'quantity': item['quantity']}
                        for item in mydict[0]['order_items']
                    ]

                    with open("logs.txt", "w") as f:
                        f.write("Items updated")
                else:
                    return jsonify({'error': 'No order_list found in response'}), 404
            else:
                return jsonify({'error': f'Request failed with status code {response.status_code}'}), 500

            # Return extracted_data as JSON response

            return jsonify(extracted_data), 200

        except Exception as e:
            return jsonify({'error': str(e)}), 500
        
    
    # ------------------------- INGREDIENTS HANDLING -------------------- #

    @app.route('/get_inventory')
    def api_inventory():
        inventory_data = read_csv('inventory.csv')
        return jsonify(inventory_data)
    
    """

    @app.route('/manage_item', methods=['POST'])
    def manage_item():
        item_name = request.form.get('ingredient')
        quantity = request.form.get('count')

        inventory = read_csv('inventory.csv')

        for item in inventory:
            if item['ingredient'] == item_name:
                item['count'] = quantity
                break
        else:
            inventory.append({'ingredient': item_name, 'count': quantity})

        write_csv('inventory.csv', inventory)

        return jsonify({'status': 'success'})

    @app.route('/delete_item', methods=['POST'])
    def delete_item():
        item_name = request.form.get('delete_item_name')
        inventory = read_csv('inventory.csv')
        inventory = [item for item in inventory if item['ingredient'] != item_name]
        write_csv('inventory.csv', inventory)

        return jsonify({'status': 'success'})

    """

    # --------------------- MENU HANDLING ---------------------- #
        
    @app.route('/check_threshold')
    def check_threshold():
        try:
            menu = read_csv('menu.csv')
            
            items_below_threshold = []
            for item in menu:
                quantity = int(item['quantity'])
                minimum_count = int(item['low_count'])
                
                if quantity < minimum_count:
                    items_below_threshold.append(item)
                    
            return jsonify(items_below_threshold), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500


    @app.route('/get_menu')
    def api_menu():
        menu_data = read_csv('menu.csv')
        return jsonify(menu_data)
    
    """

    @app.route('/manage_menu_item', methods=['POST'])
    def manage_menu_item():
        item_name = request.form.get('menu-item')
        quantity = request.form.get('quantity')

        menu = read_csv('menu.csv')

        for item in menu:
            if item['item_name'] == item_name:
                item['quantity'] = quantity
                break
        else:
            menu.append({'item_name': item_name, 'quantity': quantity})

        write_csv('menu.csv', menu)

        return jsonify({'status': 'success'})

    @app.route('/delete_menu_item', methods=['POST'])
    def delete_menu_item():
        item_name = request.form.get('delete_menu_item')
        menu = read_csv('menu.csv')
        menu = [item for item in menu if item['item_name'] != item_name]
        write_csv('menu.csv', menu)

        return jsonify({'status': 'success'})
    """

    # Flask route to check if an item is present
    @app.route('/check_item', methods=['POST'])
    def check_item():
        request_data = request.get_json()
        item_to_check = request_data.get('item_name')

        # Example: Check if item is present in a text file
        with open('item_list.txt', 'r') as file:
            item_list = file.read().splitlines()

        if item_to_check in item_list:
            return jsonify({'status': 'present'})
        else:
            return jsonify({'status': 'not_present'})
        
    # Load Excel files
    file_paths = {
        'Inventory': 'inventory.csv',
        'Menu': 'menu.csv',
        'Mappings': 'mappings.csv'
    }

    # Endpoint to load data from CSV files
    @app.route('/load_data/<filename>', methods=['GET'])
    def load_data(filename):
        if filename in file_paths:
            file_path = file_paths[filename]
            
            # Additional logic for mappings.csv
            if filename == 'Mappings':
                items = []
                with open(file_path, newline='') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        item_name = row['item']
                        ingredients = row['ingredients']
                        items.append({'item': item_name, 'ingredients': ingredients})
                return jsonify(items)
            
            elif file_path.endswith('.csv'):
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
            
            # Convert dataframe to dictionary format
            data = df.to_dict(orient='records')
            return jsonify(data)
        
        return jsonify({'error': 'File not found'}), 404

    # Endpoint to save data to CSV files
    @app.route('/save_data/<filename>', methods=['POST'])
    def save_data(filename):
        if filename in file_paths:
            data = request.json
            df = pd.DataFrame(data)
            file_path = file_paths[filename]
            if file_path.endswith('.csv'):
                df.to_csv(file_path, index=False)
            else:
                df.to_excel(file_path, index=False)
            return jsonify({'success': True})
        
        return jsonify({'error': 'File not found'}), 404

    # TELEGRAM BOT
    
    @app.route('/send_alert_bot')
    def send_alert_bot():
        try:
            menu = read_csv('menu.csv')
            inventory = read_csv('inventory.csv')
            mappings = read_csv('mappings.csv')

            MINIMUM_COUNT = int(request.args.get('min_count', 5))

            items_below_threshold_and_missing_ingredients = []

            for item in menu:
                item_name = item['item_name']
                item_quantity = int(item['quantity'])

                item_info = {
                    'item_name': item_name,
                    'quantity': item_quantity,
                    'below_threshold': item_quantity < MINIMUM_COUNT,
                    'missing_ingredients': {}
                }

                if not check_inventory_availability(item_name, item_quantity, inventory, mappings):
                    missing = calculate_missing_ingredients(item_name, item_quantity, inventory, mappings)
                    if missing:
                        item_info['missing_ingredients'] = missing

                if item_info['below_threshold'] or item_info['missing_ingredients']:
                    items_below_threshold_and_missing_ingredients.append(item_info)

                    # Craft the message to send
            message = "Alert: Items below threshold or missing ingredients:\n"
            for item in items_below_threshold_and_missing_ingredients:
                message += f"Item: {item['item_name']}, Quantity: {item['quantity']}\n"
                if item['below_threshold']:
                    message += f"  - Below threshold\n"
                if item['missing_ingredients']:
                    missing_ingredients_list = ', '.join([f"{k}: {v}" for missing in item['missing_ingredients'] for k, v in missing.items()])
                    message += f"  - Missing ingredients: {missing_ingredients_list}\n"

            send_telegram_message(message)

            return jsonify(message), 200

        except Exception as e:
            import traceback
            traceback.print_exc() 
            return jsonify({'error': str(e)}), 500

    @app.route('/send_order_complete_alert_bot', methods=['POST'])
    def send_order_complete_alert_bot():
        data = request.get_json()
        table_id = data.get('table_id')
    
        # Prepare the message to be sent to Telegram
        message = f"Order details for table {table_id} completed.\n"
        
        send_telegram_message(message)
        
        return jsonify({"message": "Order details sent to Telegram"}), 200
        

    @app.route('/get_items_below_threshold_and_missing_ingredients', methods=['GET'])
    def get_items_below_threshold_and_missing_ingredients():
        try:
            menu = read_csv('menu.csv')
            inventory = read_csv('inventory.csv')
            mappings = read_csv('mappings.csv')

            

            items_below_threshold_and_missing_ingredients = []

            for item in menu:
                item_name = item['item_name']
                item_quantity = int(item['quantity'])
                MINIMUM_COUNT = int(item['low_count'])

                item_info = {
                    'item_name': item_name,
                    'quantity': item_quantity,
                    'below_threshold': item_quantity < MINIMUM_COUNT,
                    'missing_ingredients': {}
                }

                if not check_inventory_availability(item_name, item_quantity, inventory, mappings):
                    missing = calculate_missing_ingredients(item_name, item_quantity, inventory, mappings)
                    if missing:
                        item_info['missing_ingredients'] = missing

                if item_info['below_threshold'] or item_info['missing_ingredients']:
                    items_below_threshold_and_missing_ingredients.append(item_info)

            return jsonify(items_below_threshold_and_missing_ingredients), 200

        except Exception as e:
            return jsonify({'error': str(e)}), 500
        
    
    @app.route('/display')
    def display_csv():
        csv_file_path = 'mappings.csv'
        items = []

        with open(csv_file_path, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                item_name = row['item']
                ingredients = row['ingredients']
                items.append({'item': item_name, 'ingredients': ingredients})

        return render_template('display.html', items=items)
    
    @app.route('/save_update_inventory', methods=['POST'])
    def save_update_inventory():
        data = request.get_json()

        # Load inventory DataFrame
        inventory_df = pd.read_csv(file_paths['Inventory'])

        # Print columns for debugging
        print("Inventory DataFrame columns:", inventory_df.columns)

        # Print incoming data for debugging
        print("Received data:", data)

        try:
            # Update the row based on the 'ingredient' column
            inventory_df.loc[inventory_df['ingredient'] == data['ingredient'], 'count'] = data['count']
            inventory_df.to_csv(file_paths['Inventory'], index=False)
            return jsonify({'message': 'Inventory updated successfully'}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500

        

        
    @app.route('/save_update_menu', methods=['POST'])
    def save_update_menu():
        data = request.get_json()

        try:
            # Load menu DataFrame
            menu_df = pd.read_csv(file_paths['Menu'])

            # Print columns for debugging
            print("Menu DataFrame columns:", menu_df.columns)

            # Print incoming data for debugging
            print("Received data:", data)

            # Update the row based on the 'item_name' column
            menu_df.loc[menu_df['item_name'] == data['item_name'], ['quantity', 'low_count']] = [
                data['quantity'], data['low_count']
            ]

            # Save updated DataFrame back to CSV
            menu_df.to_csv(file_paths['Menu'], index=False)

            return jsonify({'message': 'Menu item updated successfully'}), 200

        except Exception as e:
            return jsonify({'error': str(e)}), 500


    return app, socket_io
