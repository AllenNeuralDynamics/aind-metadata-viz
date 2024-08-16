import panel as pn

# Initialize Panel extension
pn.extension()

# Example parameter that you might want to change
dynamic_parameter = pn.widgets.TextInput(name='Parameter', value='Hello')

# Placeholder for JavaScript code
js_code = """
console.log("Static message");
"""

# Create a Panel HTML pane with the initial JavaScript code
js_pane = pn.pane.HTML(f"<script>{js_code}</script>", height=0, width=0)


# Function to update the JavaScript dynamically
def update_js(event):
    new_js_code = f"""
    console.log("{dynamic_parameter.value}");
    """
    js_pane.object = f"<script>{new_js_code}</script>"


# Button to trigger JavaScript update
button = pn.widgets.Button(name='Run JS', button_type='primary')

# Link button click event to update function
button.on_click(update_js)

# Layout to display everything
app = pn.Column(dynamic_parameter, button, js_pane)

app.servable()
