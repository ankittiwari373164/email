"""
Email Template Builder — generates professional HTML emails
with clean design, responsive layout, and personalization.
"""

def build_professional_html_email(
    company_name="Your Company",
    company_logo_url="",
    headline="Ready to Transform Your Business?",
    subheading="",
    intro_text="",
    features=None,
    cta_text="Get Started",
    cta_link="#",
    footer_text="",
    contact_phone="",
    contact_email="",
    contact_website="",
    sender_name="",
    personalize_name="",  # {business_name}, {city}, {category}, {email}
):
    """
    Build a professional, responsive HTML email template.
    
    Args:
        company_name: Your company/brand name
        company_logo_url: Full URL to company logo (optional)
        headline: Main headline (e.g. "Ready to Transform Your Business?")
        subheading: Optional secondary headline
        intro_text: Introductory paragraph(s)
        features: List of dicts with 'title' and 'description' keys
        cta_text: Call-to-action button text
        cta_link: CTA button link/email address
        footer_text: Footer disclaimer/closing text
        contact_phone: Phone number for footer
        contact_email: Email for footer
        contact_website: Website for footer
        sender_name: Sender's name (e.g. "Ankit Tiwari")
        personalize_name: If True, will use {business_name} in greeting
    """
    if features is None:
        features = []

    # Build features section HTML
    features_html = ""
    if features:
        features_html = '<div style="margin: 30px 0;">'
        for feature in features:
            features_html += f'''
            <div style="margin: 20px 0; padding-left: 20px; border-left: 4px solid #5b5bff;">
                <h4 style="color: #333; margin: 0 0 8px 0; font-size: 16px; font-weight: 600;">
                    ✓ {feature.get('title', '')}
                </h4>
                <p style="color: #666; margin: 0; font-size: 14px; line-height: 1.5;">
                    {feature.get('description', '')}
                </p>
            </div>
            '''
        features_html += '</div>'

    # Build contact info
    contact_html = ""
    if contact_phone:
        contact_html += f'<p style="margin: 8px 0; color: #666; font-size: 14px;"><strong>📞</strong> {contact_phone}</p>'
    if contact_email:
        contact_html += f'<p style="margin: 8px 0; color: #666; font-size: 14px;"><strong>📧</strong> <a href="mailto:{contact_email}" style="color: #5b5bff; text-decoration: none;">{contact_email}</a></p>'
    if contact_website:
        contact_html += f'<p style="margin: 8px 0; color: #666; font-size: 14px;"><strong>🌐</strong> <a href="https://{contact_website}" style="color: #5b5bff; text-decoration: none;">{contact_website}</a></p>'

    # Build logo section
    logo_html = ""
    if company_logo_url:
        logo_html = f'<div style="text-align: center; margin-bottom: 30px;"><img src="{company_logo_url}" alt="{company_name}" style="max-width: 200px; height: auto;"></div>'

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Email from {company_name}</title>
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            
            <!-- Header with gradient background -->
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 8px 8px 0 0; padding: 40px 20px; text-align: center; color: white;">
                {logo_html}
                <h1 style="margin: 0 0 10px 0; font-size: 28px; font-weight: 700; line-height: 1.3;">
                    {headline}
                </h1>
                {f'<p style="margin: 0; font-size: 16px; opacity: 0.9;">{subheading}</p>' if subheading else ''}
            </div>

            <!-- Main content -->
            <div style="background: #f9fafb; border: 1px solid #e5e7eb; border-top: none; padding: 40px 30px;">
                
                <!-- Intro text -->
                {f'<div style="color: #555; font-size: 15px; line-height: 1.8; margin-bottom: 30px;">{intro_text}</div>' if intro_text else ''}

                <!-- Features -->
                {features_html}

                <!-- CTA Button -->
                <div style="margin: 40px 0; text-align: center;">
                    <a href="{cta_link}" style="
                        display: inline-block;
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                        color: white;
                        padding: 14px 40px;
                        border-radius: 50px;
                        text-decoration: none;
                        font-weight: 600;
                        font-size: 16px;
                        transition: transform 0.2s;
                        box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
                    ">
                        {cta_text}
                    </a>
                </div>

                <!-- Footer disclaimer -->
                {f'<div style="background: #fef3c7; border-left: 4px solid #f59e0b; padding: 15px; border-radius: 4px; margin: 30px 0; color: #78350f; font-size: 13px;">{footer_text}</div>' if footer_text else ''}

            </div>

            <!-- Signature section -->
            <div style="background: #f3f4f6; border: 1px solid #e5e7eb; border-top: none; padding: 30px; border-radius: 0 0 8px 8px;">
                <p style="margin: 0 0 20px 0; color: #333; font-weight: 600;">Best Regards,</p>
                
                {f'<p style="margin: 0 0 8px 0; color: #333; font-weight: 600; font-size: 15px;">{sender_name}</p>' if sender_name else ''}
                <p style="margin: 0 0 15px 0; color: #888; font-size: 13px;">{company_name}</p>

                {contact_html}
            </div>

            <!-- Bottom disclaimer -->
            <div style="text-align: center; margin-top: 20px; font-size: 12px; color: #999;">
                <p>This email was sent to you because we believe it's relevant to your business.</p>
            </div>

        </div>
    </body>
    </html>
    """

    return html.strip()


# Pre-built templates

TEMPLATE_DIGITAL_MARKETING = {
    "name": "Digital Marketing Services",
    "subject": "Transform Your Business with {company_name} | {category} Experts",
    "config": {
        "company_name": "Your Agency",
        "headline": "Ready to Transform Your Business? 🚀",
        "subheading": "Digital Marketing Excellence",
        "intro_text": """Are you looking to grow your business, attract more customers, and establish a strong online presence? 
        
We specialize in creating custom websites, managing social media, and implementing data-driven digital marketing strategies to help businesses like yours thrive in today's competitive digital landscape.""",
        "features": [
            {
                "title": "Professional Website Development",
                "description": "A sleek, SEO-friendly website that showcases your services, products, and success stories."
            },
            {
                "title": "Social Media Management",
                "description": "Engaging content creation and daily posts across platforms like Facebook, Instagram, LinkedIn, and YouTube to increase your brand visibility."
            },
            {
                "title": "Targeted Digital Marketing",
                "description": "High-performing ad campaigns on Meta Business Suite & Google Ads to drive traffic and attract your ideal customers."
            },
            {
                "title": "Lead Generation Strategies",
                "description": "Converting potential customers into loyal clients through effective marketing techniques and data analysis."
            }
        ],
        "cta_text": "📧 Email Us Now",
        "footer_text": "💡 Limited Slots Available! Let's explore how we can help your business grow and stand out in the digital world.",
    }
}

TEMPLATE_REAL_ESTATE = {
    "name": "Real Estate Services",
    "subject": "Grow Your Real Estate Business with Expert Marketing",
    "config": {
        "company_name": "Real Estate Experts",
        "headline": "Unlock Your Property Potential 🏢",
        "subheading": "Real Estate Marketing & Lead Generation",
        "intro_text": """In today's competitive real estate market, having the right marketing strategy is crucial to attract qualified buyers and sellers.
        
Our proven strategies have helped dozens of real estate agents and brokers scale their business and close more deals faster.""",
        "features": [
            {
                "title": "Property Listing Optimization",
                "description": "Professional photography, compelling descriptions, and SEO optimization to showcase your properties to the right buyers."
            },
            {
                "title": "Targeted Lead Generation",
                "description": "Strategic digital campaigns designed to attract qualified buyers and sellers actively looking for properties in your area."
            },
            {
                "title": "Social Media Real Estate Marketing",
                "description": "Showcase properties and build your brand presence across Instagram, Facebook, and LinkedIn with engaging content."
            },
            {
                "title": "Conversion-Focused Sales Strategy",
                "description": "Turn interested leads into actual clients with proven follow-up systems and nurturing campaigns."
            }
        ],
        "cta_text": "📞 Schedule a Free Consultation",
        "footer_text": "🎯 Let's discuss how to accelerate your real estate business with data-driven marketing.",
    }
}

TEMPLATE_ECOMMERCE = {
    "name": "E-commerce Growth",
    "subject": "Boost Your Online Sales with Proven Strategies",
    "config": {
        "company_name": "E-commerce Growth Experts",
        "headline": "Ready to Skyrocket Your E-commerce Sales? 📈",
        "subheading": "Proven Strategies for Online Success",
        "intro_text": """Running an online store requires more than just listing products — it requires a comprehensive strategy to drive traffic, convert visitors, and maximize customer lifetime value.
        
We help e-commerce businesses like yours achieve sustainable growth through strategic marketing and optimization.""",
        "features": [
            {
                "title": "E-commerce SEO & Optimization",
                "description": "Improve your store's visibility in search results and optimize product pages for higher conversion rates."
            },
            {
                "title": "Paid Advertising Campaigns",
                "description": "Strategic Google Ads and Facebook/Instagram campaigns designed to attract high-intent buyers to your store."
            },
            {
                "title": "Email Marketing & Retention",
                "description": "Automated email sequences to re-engage customers, promote new products, and increase repeat purchases."
            },
            {
                "title": "Conversion Rate Optimization",
                "description": "Data-driven improvements to reduce cart abandonment, improve checkout flow, and maximize average order value."
            }
        ],
        "cta_text": "🛒 Let's Grow Your Sales",
        "footer_text": "💎 Join 100+ e-commerce businesses scaling with our proven strategies.",
    }
}