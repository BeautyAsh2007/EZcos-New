import streamlit as st
import pandas as pd
import streamlit_authenticator as stauth
from supabase import create_client
import bcrypt

# Page Configuration
st.set_page_config(page_title="Civil Engineering BOQ System", layout="wide")

# --- 1. DATABASE CONNECTION ---
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]
supabase = create_client(url, key)

# --- 2. AUTHENTICATION HELPER FUNCTIONS ---
def fetch_all_users():
    """Fetches all users explicitly targeting the public schema to avoid routing errors."""
    try:
        response = supabase.schema("public").table("profiles").select("username, name, password").execute()
        users_data = response.data
        
        credentials = {"usernames": {}}
        for user in users_data:
            credentials["usernames"][user["username"]] = {
                "name": user["name"],
                "password": user["password"]
            }
        return credentials
    except Exception as e:
        st.error(f"Database sync error: {e}")
        return {"usernames": {}}

def hash_password(password: str) -> str:
    """Hashes a plain text password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

# Load credential mapping dynamically
credentials = fetch_all_users()

authenticator = stauth.Authenticate(
    credentials,
    cookie_name="boq_auth_cookie",
    key="signature_key_secret",
    cookie_expiry_days=30
)

# --- 3. SIGN IN / SIGN UP INTERFACE ---
if not st.session_state.get("authentication_status"):
    tab1, tab2 = st.tabs(["🔐 Log In", "📝 Sign Up"])
    
    with tab1:
        authenticator.login(location="main")
        authentication_status = st.session_state.get("authentication_status")
        
        if authentication_status == False:
            st.error('Username/password is incorrect')
        elif authentication_status == None:
            st.warning('Please enter your username and password')
            
    with tab2:
        st.subheader("Create a New Account")
        new_username = st.text_input("Choose a Username", key="reg_user").strip().lower()
        new_name = st.text_input("Full Name (e.g., Juan Dela Cruz)", key="reg_name").strip()
        new_password = st.text_input("Password", type="password", key="reg_pass")
        confirm_password = st.text_input("Confirm Password", type="password", key="reg_confirm")
        
        if st.button("Register Account", use_container_width=True):
            if not new_username or not new_name or not new_password:
                st.error("All fields are required!")
            elif new_password != confirm_password:
                st.error("Passwords do not match!")
            elif len(new_password) < 6:
                st.error("Password must be at least 6 characters long.")
            else:
                existing = supabase.schema("public").table("profiles").select("username").eq("username", new_username).execute()
                if existing.data:
                    st.error("Username already taken. Please choose another.")
                else:
                    hashed_pw = hash_password(new_password)
                    supabase.schema("public").table("profiles").insert({
                        "username": new_username,
                        "name": new_name,
                        "password": hashed_pw
                    }).execute()
                    st.success("Registration successful! You can now log in on the first tab.")
                    st.rerun()

# --- 4. MAIN SYSTEM RUNS ONLY IF LOGGED IN ---
if st.session_state.get("authentication_status"):
    username = st.session_state.get("username")
    name = st.session_state.get("name")
    
    authenticator.logout('Logout', 'sidebar')
    st.title(f"🏗️ Project Cost Estimate System")
    st.subheader(f"Welcome back, Engr. {name}")
    
    # Initialize session state for active table
    if "boq_data" not in st.session_state:
        st.session_state.boq_data = pd.DataFrame(
            columns=["Item No.", "Item Description", "Unit", "Quantity", "Unit Cost", "Subtotal"]
        )

    # Initialize calculation flag state to hide total on fresh reloads
    if "show_calculated_total" not in st.session_state:
        st.session_state.show_calculated_total = False

    # --- PROJECT DASHBOARD MANAGEMENT BOX ---
    st.markdown("Project Dashboard")
    dash_col1, dash_col2 = st.columns(2)
    
    with dash_col1:
        st.subheader("💾 Save Active Project")
        proj_name = st.text_input("Enter Project Name")
        if st.button("Save Current Table to Cloud"):
            if proj_name.strip() == "":
                st.error("Please enter a valid project name.")
            else:
                json_data = st.session_state.boq_data.to_json(orient="records")
                supabase.schema("public").table("project_saves").insert({
                    "username": username,
                    "project_name": proj_name,
                    "boq_json": json_data
                }).execute()
                st.success(f"Project '{proj_name}' securely saved!")
                st.rerun()

    with dash_col2:
        st.subheader("📂 Reload Previous Calculations")
        response = supabase.schema("public").table("project_saves").select("project_name, boq_json").eq("username", username).execute()
        saved_projects = response.data
        
        if saved_projects:
            proj_options = [p["project_name"] for p in saved_projects]
            selected_project = st.selectbox("Select a project to restore:", proj_options)
            
            if st.button("Load Selected Project"):
                chosen_data = next(p for p in saved_projects if p["project_name"] == selected_project)
                restored_df = pd.read_json(chosen_data["boq_json"])
                if not restored_df.empty:
                    restored_df = restored_df[["Item No.", "Item Description", "Unit", "Quantity", "Unit Cost", "Subtotal"]]
                st.session_state.boq_data = restored_df
                st.session_state.show_calculated_total = False # Reset total display on load
                st.success(f"Successfully loaded '{selected_project}'!")
                st.rerun()
        else:
            st.info("No saved projects found for your account.")

    st.markdown("---")
    
    # --- SIDEBAR INPUT FIELDS & VALIDATION ---
    st.sidebar.header("📋 Item Input Form")
    item_desc = st.sidebar.text_input("Item Description", placeholder="e.g., Concrete Works")
    unit = st.sidebar.selectbox("Unit", ["sqm", "pcs", "cu.m", "kg", "linear m"])
    quantity = st.sidebar.number_input("Quantity", min_value=0.0, step=1.0, value=0.0)
    unit_cost = st.sidebar.number_input("Unit Cost", min_value=0.0, step=1.0, value=0.0)

    col1, col2 = st.sidebar.columns(2)

    if col1.button("➕ Add Item", use_container_width=True):
        if item_desc.strip() == "":
            st.sidebar.error("Description cannot be empty!")
        elif quantity <= 0 or unit_cost <= 0:
            st.sidebar.error("Values must be greater than 0!")
        else:
            calculated_subtotal = quantity * unit_cost
            next_no = len(st.session_state.boq_data) + 1
            new_row = pd.DataFrame([{
                "Item No.": next_no,
                "Item Description": item_desc,
                "Unit": unit,
                "Quantity": quantity,
                "Unit Cost": unit_cost,
                "Subtotal": calculated_subtotal
            }])
            st.session_state.boq_data = pd.concat([st.session_state.boq_data, new_row], ignore_index=True)
            st.session_state.show_calculated_total = False # Reset calculation output state
            st.rerun()

    if col2.button("🧹 Clear Table", use_container_width=True):
        st.session_state.boq_data = pd.DataFrame(
            columns=["Item No.", "Item Description", "Unit", "Quantity", "Unit Cost", "Subtotal"]
        )
        st.session_state.show_calculated_total = False
        st.rerun()

    # --- SIDEBAR EDITING ACTIONS PANEL ---
    if not st.session_state.boq_data.empty:
        st.sidebar.markdown("---")
        st.sidebar.header("⚙️ Data Actions Panel")
        
        selected_no = st.sidebar.selectbox("Select Target Item No.", st.session_state.boq_data["Item No."].tolist())
        idx = st.session_state.boq_data[st.session_state.boq_data["Item No."] == selected_no].index
        
        action_mode = st.sidebar.selectbox("Choose Action", ["🔄 Update Item", "❌ Delete Item"])
        
        if st.sidebar.button("Execute Action", use_container_width=True, type="secondary"):
            st.session_state.show_calculated_total = False # Reset calculation on modification
            
            if action_mode == "🔄 Update Item":
                if item_desc.strip() != "":
                    st.session_state.boq_data.at[idx, "Item Description"] = item_desc
                if quantity > 0:
                    st.session_state.boq_data.at[idx, "Quantity"] = quantity
                if unit_cost > 0:
                    st.session_state.boq_data.at[idx, "Unit Cost"] = unit_cost
                
                st.session_state.boq_data.at[idx, "Subtotal"] = (
                    st.session_state.boq_data.at[idx, "Quantity"] * st.session_state.boq_data.at[idx, "Unit Cost"]
                )
                st.sidebar.success(f"Item No. {selected_no} successfully updated!")
                st.rerun()
                
            elif action_mode == "❌ Delete Item":
                st.session_state.boq_data = st.session_state.boq_data[st.session_state.boq_data["Item No."] != selected_no].reset_index(drop=True)
                st.session_state.boq_data["Item No."] = range(1, len(st.session_state.boq_data) + 1)
                st.sidebar.success(f"Item No. {selected_no} dropped completely!")
                st.rerun()

    # --- MAIN SPREADSHEET VIEW ---
    st.markdown("### 📊 Bill of Quantities (BOQ) Spreadsheet Table")
    edited_df = st.data_editor(
        st.session_state.boq_data,
        num_rows="fixed",
        disabled=["Item No.", "Subtotal"], 
        hide_index=True,
        use_container_width=True,
        column_config={
            "Unit Cost": st.column_config.NumberColumn("Unit Cost", format="\u20b1%,.2f"),
            "Subtotal": st.column_config.NumberColumn("Subtotal", format="\u20b1%,.2f")
        }
    )

    if not edited_df.equals(st.session_state.boq_data):
        st.session_state.show_calculated_total = False # Reset calculations if direct spreadsheet grid edits happen
        edited_df["Subtotal"] = edited_df["Quantity"] * edited_df["Unit Cost"]
        st.session_state.boq_data = edited_df
        st.rerun()

    # --- SEPARATED CALCULATION LOGIC SECTION ---
    st.markdown("---")
    calc_col1, calc_col2 = st.columns([1, 3])
    
    with calc_col1:
        # Action button positioned cleanly down below the main spreadsheet view
        if st.button("🧮 Compute Grand Total", use_container_width=True, type="primary"):
            st.session_state.show_calculated_total = True
            st.rerun()
            
    with calc_col2:
        # Display cost summaries ONLY if the button above has been explicitly toggled
        if st.session_state.show_calculated_total:
            grand_total = st.session_state.boq_data["Subtotal"].sum()
            st.metric(label="💰 Grand Total Project Cost", value=f"\u20b1{grand_total:,.2f}")
        else:
            st.info("Click 'Compute Grand Total' to calculate the total budget summation.")


