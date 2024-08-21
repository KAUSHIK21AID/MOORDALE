from flask import Flask, render_template, request, redirect, url_for, send_file, flash, jsonify
import pandas as pd
from io import BytesIO
import os
from docx import Document
import google.generativeai as genai
from scholarly import scholarly
import concurrent.futures

app = Flask(__name__)
app.secret_key = 'supersecretkey'  # Ensure you have a secret key for sessions and flash messages

# Initialize Google Generative AI
genai.configure(api_key="AIzaSyDJkX7rIew0l3siFeVYZAIh2xNVGsavmRk") # Replace with your actual API key
model = genai.GenerativeModel('gemini-1.5-flash-latest')

# Global variables
processed_df = None  # Placeholder for DataFrame
results_html = None  # Placeholder for HTML table

# Function to retrieve scholarly information
def retrieve_stuffs(author_name, institution_name):
    try:
        search_query = f"{author_name} {institution_name}"
        search_result = scholarly.search_author(search_query)
        first_author_result = next(search_result)
        author = scholarly.fill(first_author_result)

        titles = []
        years = []
        citation = []

        for pub in author['publications']:
            titles.append(pub['bib']['title'])
            years.append(pub['bib'].get('pub_year'))
            citation.append(pub['bib'].get('citation', '').lower())

        df = pd.DataFrame({
            'Author': [author_name] * len(author['publications']),
            'Title': titles,
            'Publication Year': years,
            'Citation': citation,
            'Institution_Name': institution_name  # Added institution name
        })

        return df
    except StopIteration:
        print(f"Author not found: {author_name}")
        return pd.DataFrame()  # Return an empty DataFrame if no results are found
    except Exception as e:
        print(f"Error processing {author_name}: {e}")
        return pd.DataFrame()  # Return an empty DataFrame in case of error

def generate_author_summary(df, author):
    filtered_df = df[df['Author'] == author]
    if filtered_df.empty:
        return f"No publications found for author '{author}'"

    titles = filtered_df['Title'].tolist()
    citations = filtered_df['Citation'].tolist()
    intro_phrases = [
        "One of the key works was",
        "Another notable publication was",
        "Among the significant contributions was",
        "An important study was",
        "A remarkable work was",
        "Additionally, there was",
        "Another critical work was"
    ]
    summary = f"{author} made significant contributions to their field with several impactful publications. "
    for i, (title, citation) in enumerate(zip(titles, citations)):
        phrase = intro_phrases[i % len(intro_phrases)]  # Cycle through phrases
        summary += f"{phrase} '{title}', which appeared in {citation}. "
    summary += f"These publications underscore {author}'s commitment to advancing research in their domain, particularly in areas such as {', '.join([title.split(':')[0].lower() for title in titles[:2]])}, and other related fields."
    SYSTEM_PROMPT = "Your name is Summarize AI. Your task is to Summarize the context."

    chat = model.start_chat(history=[{"role": "model", "parts": [SYSTEM_PROMPT]}])
    response = chat.send_message(f"""
User Prompt: Summarize the following text.
\n\n
Here is the Text: {summary}
\n\n
Instruction:
Generate a concise summary of the provided text.
""", stream=True)

    final_summary = ""
    for chunk in response:
        final_summary += chunk.text

    return final_summary

def generate_word_doc(summary_text):
    doc = Document()
    doc.add_heading('Customized Summary', level=1)
    doc.add_paragraph(summary_text)
    return doc

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        flash('No file part')
        return redirect(request.url)

    file = request.files['file']

    if file.filename == '':
        flash('No selected file')
        return redirect(request.url)

    if file:
        try:
            # Read the uploaded CSV file
            df = pd.read_csv(file)
            combined_df = pd.DataFrame()

            # Process each author in the CSV file
            institution_name = df['Institution_Name'].iloc[0] if 'Institution_Name' in df.columns else ''
            author_list = df['Author'].tolist()

            with concurrent.futures.ThreadPoolExecutor() as executor:
                results = list(executor.map(lambda name: retrieve_stuffs(name, institution_name), author_list))

            for result in results:
                combined_df = pd.concat([combined_df, result], ignore_index=True)

            # Save the dataframe as a global variable and HTML table
            global processed_df, results_html
            processed_df = combined_df
            results_html = combined_df.to_html(classes='table dataTable', index=False)

            # Redirect to results page
            return redirect(url_for('results'))

        except Exception as e:
            flash(f'An error occurred while processing the file: {str(e)}')
            return redirect(url_for('index'))

@app.route('/results')
def results():
    if processed_df is None:
        flash("No results to display. Please upload and process a CSV first.")
        return redirect(url_for('index'))
    
    global results_html
    results_html = processed_df.to_html(classes='table dataTable', index=False)
    return render_template('results.html', results=results_html, authors=processed_df['Author'].unique().tolist())

@app.route('/summary', methods=['POST'])
def summary():
    author = request.form.get('author')
    if author:
        summary_text = generate_author_summary(processed_df, author)
        return jsonify({'summary': summary_text})
    else:
        return jsonify({'summary': 'No author selected.'})

@app.route('/download_summary', methods=['GET'])
def download_summary():
    author = request.args.get('author')
    if author:
        summary_text = generate_author_summary(processed_df, author)
        summary_doc = generate_word_doc(summary_text)
        summary_buffer = BytesIO()
        summary_doc.save(summary_buffer)
        summary_buffer.seek(0)
        return send_file(summary_buffer, as_attachment=True, download_name=f"{author}_summary.docx", mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    else:
        flash("No author selected.")
        return redirect(url_for('results'))

@app.route('/download')
def download():
    if processed_df is None:
        flash("No data to download. Please upload and process a CSV first.")
        return redirect(url_for('index'))

    csv_buffer = BytesIO()
    processed_df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)
    
    return send_file(csv_buffer, as_attachment=True, download_name='results.csv', mimetype='text/csv')

if __name__ == '__main__':
    app.run(debug=True)
