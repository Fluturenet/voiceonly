# app/utils/rss.py
from datetime import datetime
from typing import List, Optional, Dict
import xml.etree.ElementTree as ET
from xml.dom import minidom
import email.utils
from app.config import settings

def format_rfc822_date(timestamp: float) -> str:
    """Format timestamp for RSS pubDate (RFC 2822)"""
    return email.utils.formatdate(timestamp, localtime=False)

def escape_xml(text: Optional[str]) -> str:
    """Escape special characters for XML"""
    if text is None:
        return ""
    text = str(text)
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')
    text = text.replace("'", '&apos;')
    return text

def generate_podcast_feed(
    channel_info: Dict,
    episodes: List[Dict],
    base_url: str
) -> str:
    """
    Generate iTunes-compatible podcast RSS feed
    
    Args:
        channel_info: Channel information (name, description, thumbnail, etc.)
        episodes: List of episodes (videos)
        base_url: Base URL for the server (for enclosure links)
    
    Returns:
        RSS feed as XML string
    """

    episodes.sort(key=lambda x: x.get('upload_timestamp', 0), reverse=True)

    # Create root element
    rss = ET.Element('rss', {
        'version': '2.0',
        'xmlns:itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd',
        'xmlns:content': 'http://purl.org/rss/1.0/modules/content/',
        'xmlns:atom': 'http://www.w3.org/2005/Atom'
    })
    
    channel = ET.SubElement(rss, 'channel')
    
    # Basic channel info
    ET.SubElement(channel, 'title').text = escape_xml(
        channel_info.get('name', 'Unknown Channel')
    )
    ET.SubElement(channel, 'link').text = escape_xml(
        channel_info.get('url', '')
    )
    ET.SubElement(channel, 'language').text = 'it'
    ET.SubElement(channel, 'description').text = escape_xml(
        channel_info.get('description', 'Podcast feed for YouTube channel')
    )
    
    # iTunes specific tags
    ET.SubElement(channel, 'itunes:author').text = escape_xml(
        channel_info.get('name', 'Unknown')
    )
    
    # iTunes category
    category = ET.SubElement(channel, 'itunes:category', {
        'text': channel_info.get('category', 'Music')
    })
    
    # iTunes explicit (default to No)
    ET.SubElement(channel, 'itunes:explicit').text = channel_info.get('explicit', 'No')
    
    # iTunes image
    if channel_info.get('thumbnail'):
        ET.SubElement(channel, 'itunes:image', {
            'href': channel_info['thumbnail']
        })
    
    # Owner info (optional)
    if channel_info.get('owner_name') and channel_info.get('owner_email'):
        owner = ET.SubElement(channel, 'itunes:owner')
        ET.SubElement(owner, 'itunes:name').text = escape_xml(channel_info['owner_name'])
        ET.SubElement(owner, 'itunes:email').text = escape_xml(channel_info['owner_email'])
    
    # Add episodes
    for episode in episodes:
        item = ET.SubElement(channel, 'item')
        
        # Title
        ET.SubElement(item, 'title').text = escape_xml(episode.get('title', 'Untitled'))
        
        # Description
        description = episode.get('description', '')
        if description:
            ET.SubElement(item, 'description').text = escape_xml(description)
            # Also add as content:encoded for rich text
            content = ET.SubElement(item, 'content:encoded')
            content.text = f'<![CDATA[{description}]]>'
        
        # Link to YouTube video
        ET.SubElement(item, 'link').text = escape_xml(
            f"https://youtube.com/watch?v={episode.get('video_id')}"
        )
        
        # GUID (unique identifier)
        guid = ET.SubElement(item, 'guid', {'isPermaLink': 'false'})
        guid.text = escape_xml(episode.get('video_id', ''))
        
        # Publication date
        if episode.get('upload_timestamp'):
            pub_date = ET.SubElement(item, 'pubDate')
            pub_date.text = format_rfc822_date(episode['upload_timestamp'])
        
        # Enclosure (audio file)
        if episode.get('file_path'):
            file_url = f"{base_url}/download/{episode['video_id']}?token={settings.TOKEN}"
            ET.SubElement(item, 'enclosure', {
                'url': file_url,
                'length': str(episode.get('file_size', 0)),
                'type': 'audio/opus'
            })
        
        # iTunes duration
        if episode.get('duration'):
            duration = episode['duration']
            # Format as HH:MM:SS or MM:SS
            hours = duration // 3600
            minutes = (duration % 3600) // 60
            seconds = duration % 60
            
            if hours > 0:
                duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            else:
                duration_str = f"{minutes:02d}:{seconds:02d}"
            
            ET.SubElement(item, 'itunes:duration').text = duration_str
        
        # iTunes image (episode thumbnail)
        if episode.get('thumbnail_url'):
            ET.SubElement(item, 'itunes:image', {
                'href': episode['thumbnail_url']
            })
        
        # iTunes explicit per episode
        ET.SubElement(item, 'itunes:explicit').text = episode.get('explicit', 'No')
    
    # Pretty print XML
    xml_str = ET.tostring(rss, encoding='unicode')
    dom = minidom.parseString(xml_str)
    pretty_xml = dom.toprettyxml(indent='  ', encoding='UTF-8').decode('UTF-8')
    
    # Remove XML declaration (we'll add our own)
    lines = pretty_xml.split('\n')[1:]  # Skip first line with XML declaration
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + '\n'.join(lines)