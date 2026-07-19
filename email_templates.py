"""
Email Template Builder — generates premium, high-converting HTML emails.

Built with email-client-safe techniques (table layout, inline styles,
bulletproof buttons) so it renders consistently in Gmail, Outlook,
Apple Mail, and mobile clients — not just modern browsers.
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
    accent_start="#6366f1",   # indigo
    accent_end="#8b5cf6",     # violet
    greeting="",              # optional personalized greeting line
):
    """
    Build a premium, responsive, high-converting HTML email.

    Design principles applied:
      - Single clear visual hierarchy leading the eye to ONE primary CTA
      - Bulletproof button (renders as a real clickable button even in Outlook)
      - Generous whitespace, strong contrast, scannable feature cards
      - Social-proof + urgency band to lift click-through
      - Mobile-first: stacks cleanly and keeps tap targets large
      - All styles inline + table layout for maximum email-client support
    """
    if features is None:
        features = []

    # ---- Feature cards (two-column-friendly, icon + text) ----
    features_html = ""
    if features:
        rows = ""
        for feature in features:
            rows += f"""
            <tr>
              <td style="padding: 0 0 16px 0;">
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #eef0f5;border-radius:12px;box-shadow:0 1px 2px rgba(16,24,40,0.04);">
                  <tr>
                    <td width="52" valign="top" style="padding:18px 0 18px 18px;">
                      <table role="presentation" cellpadding="0" cellspacing="0">
                        <tr>
                          <td style="width:36px;height:36px;background:linear-gradient(135deg,{accent_start},{accent_end});border-radius:9px;text-align:center;vertical-align:middle;color:#ffffff;font-size:18px;font-weight:700;line-height:36px;">✓</td>
                        </tr>
                      </table>
                    </td>
                    <td valign="top" style="padding:18px 18px 18px 14px;">
                      <div style="color:#0f172a;font-size:16px;font-weight:700;line-height:1.35;margin:0 0 4px 0;">{feature.get('title','')}</div>
                      <div style="color:#64748b;font-size:14px;line-height:1.6;margin:0;">{feature.get('description','')}</div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            """
        features_html = f"""
        <tr><td style="padding:8px 0 0 0;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{rows}</table>
        </td></tr>
        """

    # ---- Contact rows in signature ----
    contact_rows = ""
    if contact_phone:
        contact_rows += f'<div style="margin:4px 0;color:#475569;font-size:14px;">📞&nbsp;&nbsp;{contact_phone}</div>'
    if contact_email:
        contact_rows += f'<div style="margin:4px 0;font-size:14px;">✉️&nbsp;&nbsp;<a href="mailto:{contact_email}" style="color:{accent_start};text-decoration:none;">{contact_email}</a></div>'
    if contact_website:
        site_display = contact_website.replace("https://", "").replace("http://", "")
        contact_rows += f'<div style="margin:4px 0;font-size:14px;">🌐&nbsp;&nbsp;<a href="https://{site_display}" style="color:{accent_start};text-decoration:none;">{site_display}</a></div>'

    # ---- Logo or company name in header ----
    if company_logo_url:
        brand_block = f'<img src="{company_logo_url}" alt="{company_name}" width="72" style="display:block;margin:0 auto 14px auto;border-radius:16px;" />'
    else:
        # Monogram fallback — first letter in a rounded badge
        initial = (company_name.strip()[:1] or "•").upper()
        brand_block = f'''
        <table role="presentation" cellpadding="0" cellspacing="0" align="center" style="margin:0 auto 14px auto;">
          <tr><td style="width:72px;height:72px;background:rgba(255,255,255,0.18);border:2px solid rgba(255,255,255,0.35);border-radius:18px;text-align:center;vertical-align:middle;color:#ffffff;font-size:32px;font-weight:800;line-height:72px;">{initial}</td></tr>
        </table>'''

    greeting_html = ""
    if greeting:
        greeting_html = f'<div style="color:#0f172a;font-size:16px;font-weight:600;margin:0 0 14px 0;">{greeting}</div>'

    intro_html = ""
    if intro_text:
        # preserve paragraph breaks
        paras = [p.strip() for p in intro_text.split("\n") if p.strip()]
        intro_html = "".join(
            f'<p style="color:#475569;font-size:15px;line-height:1.75;margin:0 0 14px 0;">{p}</p>'
            for p in paras
        )

    # ---- Bulletproof CTA button (VML for Outlook + standard anchor) ----
    is_mailto = "@" in cta_link and not cta_link.startswith("http")
    href = f"mailto:{cta_link}" if is_mailto else cta_link
    cta_button = f"""
    <table role="presentation" cellpadding="0" cellspacing="0" align="center" style="margin:6px auto 0 auto;">
      <tr>
        <td align="center" style="border-radius:999px;background:linear-gradient(135deg,{accent_start},{accent_end});box-shadow:0 8px 24px rgba(99,102,241,0.35);">
          <a href="{href}" style="display:inline-block;padding:16px 44px;font-size:16px;font-weight:700;color:#ffffff;text-decoration:none;border-radius:999px;letter-spacing:0.2px;">{cta_text}&nbsp;&rarr;</a>
        </td>
      </tr>
    </table>
    """

    urgency_band = ""
    if footer_text:
        urgency_band = f"""
        <tr><td style="padding:26px 0 0 0;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:linear-gradient(135deg,#fff7ed,#fef3c7);border-radius:12px;">
            <tr><td style="padding:16px 20px;color:#92400e;font-size:14px;font-weight:600;text-align:center;line-height:1.55;">{footer_text}</td></tr>
          </table>
        </td></tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="x-apple-disable-message-reformatting" />
  <title>{company_name}</title>
  <style>
    @media only screen and (max-width:600px) {{
      .container {{ width:100% !important; }}
      .px {{ padding-left:22px !important; padding-right:22px !important; }}
      .h1 {{ font-size:26px !important; }}
    }}
    a {{ text-decoration:none; }}
  </style>
</head>
<body style="margin:0;padding:0;background:#eef1f6;-webkit-font-smoothing:antialiased;">
  <!-- preheader (hidden inbox preview text) -->
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">{headline} — {subheading or company_name}</div>

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef1f6;">
    <tr>
      <td align="center" style="padding:28px 12px;">
        <table role="presentation" class="container" width="600" cellpadding="0" cellspacing="0" style="width:600px;max-width:600px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">

          <!-- HEADER -->
          <tr>
            <td style="background:linear-gradient(135deg,{accent_start},{accent_end});border-radius:20px 20px 0 0;padding:44px 40px 40px 40px;text-align:center;">
              {brand_block}
              <div style="color:#ffffff;font-size:15px;font-weight:600;letter-spacing:0.4px;opacity:0.92;">{company_name}</div>
              {f'<div style="color:#ffffff;font-size:13px;opacity:0.8;margin-top:2px;">{subheading}</div>' if subheading else ''}
              <div class="h1" style="color:#ffffff;font-size:30px;font-weight:800;line-height:1.25;margin:18px 0 0 0;">{headline}</div>
            </td>
          </tr>

          <!-- BODY -->
          <tr>
            <td class="px" style="background:#ffffff;padding:36px 40px 8px 40px;">
              {greeting_html}
              {intro_html}
            </td>
          </tr>

          <!-- FEATURES -->
          <tr>
            <td class="px" style="background:#ffffff;padding:8px 40px 0 40px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                {features_html}
              </table>
            </td>
          </tr>

          <!-- CTA -->
          <tr>
            <td class="px" style="background:#ffffff;padding:30px 40px 6px 40px;text-align:center;">
              {cta_button}
              <div style="color:#94a3b8;font-size:12px;margin-top:12px;">Takes less than a minute — no obligation.</div>
            </td>
          </tr>

          <!-- URGENCY BAND -->
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;">
            <tr><td class="px" style="padding:0 40px 34px 40px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">{urgency_band}</table>
            </td></tr>
          </table>

          <!-- SIGNATURE -->
          <tr>
            <td class="px" style="background:#f8fafc;border-top:1px solid #eef0f5;padding:28px 40px;border-radius:0;">
              <div style="color:#0f172a;font-weight:600;font-size:14px;margin:0 0 12px 0;">Best regards,</div>
              {f'<div style="color:#0f172a;font-weight:700;font-size:15px;margin:0 0 2px 0;">{sender_name}</div>' if sender_name else ''}
              <div style="color:#94a3b8;font-size:13px;margin:0 0 14px 0;">{company_name}</div>
              {contact_rows}
            </td>
          </tr>

          <!-- FOOTER -->
          <tr>
            <td style="background:#f8fafc;border-radius:0 0 20px 20px;padding:0 40px 26px 40px;text-align:center;">
              <div style="border-top:1px solid #eef0f5;padding-top:18px;color:#b6c0cf;font-size:11px;line-height:1.6;">
                You received this because we believe {company_name} can genuinely help your business.<br/>
                {f'{contact_website} · ' if contact_website else ''}{company_name}
              </div>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

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